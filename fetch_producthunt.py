"""Collect recent Product Hunt products by topic and vote count.

This script uses Product Hunt's official GraphQL API. Create a developer token
in the Product Hunt API dashboard and expose it as PRODUCTHUNT_ACCESS_TOKEN.

Default behavior intentionally fetches up to 20 products per run. Product Hunt
applies complexity-based API rate limits, so 20 is a safer review/default batch
size than large one-shot requests like 100.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


# Official Product Hunt GraphQL endpoint.
API_URL = "https://api.producthunt.com/v2/api/graphql"

# The two Product Hunt topics required by the original task.
DEFAULT_TOPICS = ("developer-tools", "productivity")

# Keep defaults moderate so a normal run gets useful data without using a
# high-complexity `first: 100` query.
DEFAULT_PAGE_SIZE = 20
DEFAULT_LIMIT = 20
CHECKPOINT_FILENAME = "checkpoint.json"
CONFIG_FILENAME = "config.json"
DEFAULT_OUTPUT_PREFIX = "producthunt_products"

# Project-level defaults. `config.json` can override these without changing
# code, and command-line flags can override the config for one-off runs.
DEFAULT_CONFIG: dict[str, Any] = {
    "topics": list(DEFAULT_TOPICS),
    "days": 30,
    "min_votes": 500,
    "limit": DEFAULT_LIMIT,
    "page_size": DEFAULT_PAGE_SIZE,
    "timeout": 30,
    "out_dir": "data",
    "output_prefix": DEFAULT_OUTPUT_PREFIX,
    "collect_comments": True,
    "comments_per_product": 5,
    "wait_on_rate_limit": False,
    "resume": True,
}

# Query posts for one topic at a time. We sort by votes, not newest, because the
# script only needs products above a vote threshold; this lets us stop as soon as
# the API starts returning products that are too low-vote.
POSTS_QUERY = """
query FetchPosts(
  $topic: String!
  $postedAfter: DateTime!
  $postedBefore: DateTime!
  $after: String
  $first: Int!
) {
  posts(
    first: $first
    after: $after
    order: VOTES
    topic: $topic
    postedAfter: $postedAfter
    postedBefore: $postedBefore
  ) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        name
        tagline
        description
        url
        website
        votesCount
        commentsCount
        featuredAt
        createdAt
        topics(first: 20) {
          nodes {
            name
            slug
          }
        }
      }
    }
  }
}
"""

POST_COMMENTS_QUERY = """
query FetchPostComments($id: ID!, $first: Int!) {
  post(id: $id) {
    id
    commentsCount
    comments(first: $first, order: VOTES_COUNT) {
      nodes {
        id
        body
        createdAt
        url
        votesCount
        user {
          name
          username
          url
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class Product:
    """Normalized product record used by both CSV and JSON writers."""

    id: str
    name: str
    tagline: str
    description: str
    website_url: str
    producthunt_url: str
    votes_count: int
    comments_count: int
    comments: list[dict[str, Any]]
    topics: list[str]
    topic_slugs: list[str]
    featured_at: str
    created_at: str


class ProductHuntError(RuntimeError):
    """Raised when Product Hunt API access fails."""


class ProductHuntRateLimitError(ProductHuntError):
    """Raised when Product Hunt asks the client to wait before retrying."""

    def __init__(self, retry_after: int | None) -> None:
        # Store the parsed wait time so callers/tests can inspect it if needed.
        self.retry_after = retry_after
        suffix = f" Retry after about {retry_after} seconds." if retry_after else ""
        super().__init__(f"Product Hunt rate limit reached.{suffix}")


def slugify_topic(value: str) -> str:
    """Normalize a topic name or slug into a comparable slug string."""

    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-")


def utc_now() -> datetime:
    """Return timezone-aware UTC time for date-window calculations."""

    return datetime.now(timezone.utc)


def local_now() -> datetime:
    """Return local time for user-facing folder and file names."""

    return datetime.now()


def isoformat_z(value: datetime) -> str:
    """Format datetimes in the `...Z` shape expected by Product Hunt."""

    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_datetime(value: str | None) -> datetime | None:
    """Parse Product Hunt ISO timestamps safely.

    Product Hunt returns UTC timestamps with a trailing `Z`. Python's
    `fromisoformat` expects `+00:00`, so we translate that suffix first.
    """

    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def topic_matches(post: dict[str, Any], target_slugs: set[str]) -> bool:
    """Return True when the post contains one of the requested topics."""

    topics = post.get("topics", {}).get("nodes", [])
    post_slugs = {slugify_topic(topic.get("slug") or topic.get("name") or "") for topic in topics}
    return bool(post_slugs & target_slugs)


def normalize_product(post: dict[str, Any]) -> Product:
    """Convert Product Hunt's nested GraphQL post object into our flat model."""

    topic_nodes = post.get("topics", {}).get("nodes", [])
    topics = [topic.get("name", "") for topic in topic_nodes if topic.get("name")]
    topic_slugs = [topic.get("slug", "") for topic in topic_nodes if topic.get("slug")]

    # `or ""` keeps CSV/JSON output stable even if the API omits optional fields.
    return Product(
        id=str(post.get("id", "")),
        name=post.get("name") or "",
        tagline=post.get("tagline") or "",
        description=post.get("description") or "",
        website_url=post.get("website") or "",
        producthunt_url=post.get("url") or "",
        votes_count=int(post.get("votesCount") or 0),
        comments_count=int(post.get("commentsCount") or 0),
        comments=normalize_comments(post.get("comments", {}).get("nodes", [])),
        topics=topics,
        topic_slugs=topic_slugs,
        featured_at=post.get("featuredAt") or "",
        created_at=post.get("createdAt") or "",
    )


def normalize_comments(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize Product Hunt comment nodes into JSON-safe dictionaries."""

    comments: list[dict[str, Any]] = []
    for node in nodes:
        user = node.get("user") or {}
        comments.append(
            {
                "id": str(node.get("id", "")),
                "body": node.get("body") or "",
                "created_at": node.get("createdAt") or "",
                "url": node.get("url") or "",
                "votes_count": int(node.get("votesCount") or 0),
                "user_name": user.get("name") or "",
                "user_username": user.get("username") or "",
                "user_url": user.get("url") or "",
            }
        )
    return comments


def graphql_request(
    token: str,
    query: str,
    variables: dict[str, Any],
    timeout: int,
    wait_on_rate_limit: bool,
) -> dict[str, Any]:
    """Send one GraphQL request and return the GraphQL `data` object.

    When `wait_on_rate_limit` is False, a 429 fails fast with a clear message.
    When it is True, the script sleeps for Product Hunt's suggested wait time
    and retries the same request. This is useful for full exports, but slow for
    normal review runs.
    """

    while True:
        # Keep the token only in the Authorization header. The script never logs
        # or writes this value.
        response = requests.post(
            API_URL,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": variables},
            timeout=timeout,
        )

        if response.status_code != 429:
            break

        # Product Hunt's reset header currently contains a wait duration in
        # seconds. If parsing fails, fall back to a conservative 15 minutes.
        retry_after = parse_retry_after(response.headers.get("X-Rate-Limit-Reset"))
        if not wait_on_rate_limit:
            raise ProductHuntRateLimitError(retry_after)

        wait_seconds = retry_after or 900
        print(f"Product Hunt rate limit reached. Waiting {wait_seconds} seconds before retrying...", file=sys.stderr)
        time.sleep(wait_seconds + 2)

    if response.status_code == 401:
        raise ProductHuntError("Product Hunt rejected the token. Check PRODUCTHUNT_ACCESS_TOKEN.")
    if response.status_code >= 400:
        raise ProductHuntError(f"Product Hunt API returned HTTP {response.status_code}: {response.text[:500]}")

    payload = response.json()
    # GraphQL can return HTTP 200 with an `errors` field, so check it separately.
    if payload.get("errors"):
        raise ProductHuntError(f"Product Hunt GraphQL error: {json.dumps(payload['errors'], ensure_ascii=False)}")
    return payload["data"]


def parse_retry_after(value: str | None) -> int | None:
    """Parse Product Hunt rate-limit reset seconds from a response header."""

    if not value:
        return None
    try:
        return max(0, int(float(value)))
    except ValueError:
        return None


def fetch_topic_page(
    token: str,
    topic_slug: str,
    posted_after: datetime,
    posted_before: datetime,
    after: str | None,
    page_size: int,
    timeout: int,
    wait_on_rate_limit: bool,
) -> dict[str, Any]:
    """Fetch one Product Hunt page for one topic."""

    # Cursor pagination variables. `after=None` means "first page".
    variables = {
        "topic": topic_slug,
        "postedAfter": isoformat_z(posted_after),
        "postedBefore": isoformat_z(posted_before),
        "after": after,
        "first": page_size,
    }
    return graphql_request(token, POSTS_QUERY, variables, timeout, wait_on_rate_limit)["posts"]


def fetch_post_comments(
    token: str,
    product_id: str,
    comments_per_product: int,
    timeout: int,
    wait_on_rate_limit: bool,
) -> tuple[int, list[dict[str, Any]]]:
    """Fetch a small top-voted comment sample for one product."""

    if comments_per_product <= 0:
        return 0, []

    data = graphql_request(
        token,
        POST_COMMENTS_QUERY,
        {"id": product_id, "first": comments_per_product},
        timeout,
        wait_on_rate_limit,
    )
    post = data.get("post") or {}
    return int(post.get("commentsCount") or 0), normalize_comments(post.get("comments", {}).get("nodes", []))


def collect_products(
    token: str,
    days: int,
    min_votes: int,
    topics: list[str],
    page_size: int,
    timeout: int,
    wait_on_rate_limit: bool,
    limit: int,
    collect_comments: bool,
    comments_per_product: int,
    checkpoint_path: Path,
    resume: bool,
) -> list[Product]:
    """Fetch, filter, deduplicate, sort, and checkpoint matching products."""

    # Validate CLI inputs early so failures happen before any API call.
    if days <= 0:
        raise ValueError("--days must be greater than 0")
    if min_votes < 0:
        raise ValueError("--min-votes must be 0 or greater")
    if page_size <= 0 or page_size > 100:
        raise ValueError("--page-size must be between 1 and 100")
    if limit < 0:
        raise ValueError("--limit must be 0 or greater")
    if comments_per_product < 0:
        raise ValueError("--comments-per-product must be 0 or greater")

    posted_before = utc_now()
    posted_after = posted_before - timedelta(days=days)

    params = make_checkpoint_params(days, min_votes, topics)
    target_slugs = set(params["topics"])

    checkpoint = load_checkpoint(checkpoint_path, params, resume)
    products_by_id = checkpoint_products(checkpoint)

    # Once all target topics have been fully scanned, repeated double-click runs
    # should not call Product Hunt again. They simply rewrite the existing
    # accumulated output files from the checkpoint.
    if checkpoint.get("exhausted"):
        return sorted(products_by_id.values(), key=lambda product: product.votes_count, reverse=True)

    # `limit` means "fetch up to this many new products in this batch". If a
    # prior run stopped mid-batch, the saved target is reused so the next run
    # completes the interrupted batch instead of starting a bigger one.
    current_count = len(products_by_id)
    if checkpoint.get("batch_target_count") is None:
        checkpoint["batch_target_count"] = None if limit == 0 else current_count + limit
        save_checkpoint(checkpoint_path, checkpoint)

    target_count = checkpoint.get("batch_target_count")
    while target_count is None or len(products_by_id) < target_count:
        topic_order = checkpoint.get("topic_order") or []
        topic_index = int(checkpoint.get("current_topic_index") or 0)
        if topic_index >= len(topic_order):
            checkpoint["exhausted"] = True
            checkpoint["batch_target_count"] = None
            sync_checkpoint_products(checkpoint, products_by_id)
            save_checkpoint(checkpoint_path, checkpoint)
            break

        topic_slug = topic_order[topic_index]
        completed_topics = set(checkpoint.get("completed_topics") or [])
        if topic_slug in completed_topics:
            checkpoint["current_topic_index"] = topic_index + 1
            save_checkpoint(checkpoint_path, checkpoint)
            continue

        after = checkpoint.get("topic_cursors", {}).get(topic_slug)

        # Save the last safe cursor before each request. If the process is
        # interrupted during the network call, the next run repeats at most this
        # one page and deduplication prevents duplicate output rows.
        checkpoint["last_request"] = {
            "topic": topic_slug,
            "after": after,
            "first": page_size,
            "requested_at": isoformat_z(utc_now()),
            "collected_count": len(products_by_id),
        }
        sync_checkpoint_products(checkpoint, products_by_id)
        save_checkpoint(checkpoint_path, checkpoint)

        posts = fetch_topic_page(
            token,
            topic_slug,
            posted_after,
            posted_before,
            after,
            page_size,
            timeout,
            wait_on_rate_limit,
        )

        edges = posts.get("edges", [])
        stop_after_page = False
        stopped_before_page_end = False
        for edge_index, edge in enumerate(edges):
            post = edge.get("node")
            if not post:
                continue

            # Central filtering is repeated here even though the GraphQL query
            # already narrows by topic/date. This protects the output if the API
            # shape or topic matching behavior changes.
            post_date = parse_datetime(post.get("featuredAt")) or parse_datetime(post.get("createdAt"))
            if post_date and post_date < posted_after:
                stop_after_page = True
                continue
            if int(post.get("votesCount") or 0) <= min_votes:
                stop_after_page = True
                continue
            if not topic_matches(post, target_slugs):
                continue

            product = normalize_product(post)
            if product.id:
                if collect_comments and comments_per_product > 0:
                    comments_count, comments = fetch_post_comments(
                        token,
                        product.id,
                        comments_per_product,
                        timeout,
                        wait_on_rate_limit,
                    )
                    product = replace(product, comments_count=comments_count, comments=comments)
                products_by_id[product.id] = product
                if target_count is not None and len(products_by_id) >= target_count:
                    stopped_before_page_end = edge_index < len(edges) - 1
                    break

        page_info = posts.get("pageInfo", {})
        has_next_page = bool(page_info.get("hasNextPage"))
        next_cursor = page_info.get("endCursor")

        if stopped_before_page_end:
            # Do not advance the cursor if this run stopped before processing
            # the whole page. The next batch can repeat this page and dedupe IDs,
            # which is safer than skipping unprocessed products.
            pass
        elif stop_after_page or not has_next_page or not next_cursor:
            completed_topics.add(topic_slug)
            checkpoint["completed_topics"] = sorted(completed_topics)
            checkpoint["current_topic_index"] = topic_index + 1
            if checkpoint["current_topic_index"] >= len(checkpoint.get("topic_order") or []):
                checkpoint["exhausted"] = True
                checkpoint["batch_target_count"] = None
        else:
            # Product Hunt uses opaque cursors; store and pass them unchanged.
            checkpoint.setdefault("topic_cursors", {})[topic_slug] = next_cursor

        checkpoint["last_request"] = None
        sync_checkpoint_products(checkpoint, products_by_id)
        save_checkpoint(checkpoint_path, checkpoint)

    if target_count is not None and len(products_by_id) >= target_count:
        # Mark this batch complete. The next run will create a new target of
        # "current count + limit" and continue from the saved cursors.
        checkpoint["batch_target_count"] = None
        sync_checkpoint_products(checkpoint, products_by_id)
        save_checkpoint(checkpoint_path, checkpoint)

    return sorted(products_by_id.values(), key=lambda product: product.votes_count, reverse=True)


def product_to_json_row(product: Product) -> dict[str, Any]:
    """Convert the normalized Product object into a serializable dictionary."""

    return {
        "id": product.id,
        "name": product.name,
        "tagline": product.tagline,
        "description": product.description,
        "website_url": product.website_url,
        "producthunt_url": product.producthunt_url,
        "votes_count": product.votes_count,
        "comments_count": product.comments_count,
        "comments": product.comments,
        "topics": product.topics,
        "topic_slugs": product.topic_slugs,
        "featured_at": product.featured_at,
        "created_at": product.created_at,
    }


def product_from_json_row(row: dict[str, Any]) -> Product:
    """Rebuild a Product from checkpoint/output JSON data."""

    return Product(
        id=str(row.get("id", "")),
        name=row.get("name") or "",
        tagline=row.get("tagline") or "",
        description=row.get("description") or "",
        website_url=row.get("website_url") or "",
        producthunt_url=row.get("producthunt_url") or "",
        votes_count=int(row.get("votes_count") or 0),
        comments_count=int(row.get("comments_count") or 0),
        comments=list(row.get("comments") or []),
        topics=list(row.get("topics") or []),
        topic_slugs=list(row.get("topic_slugs") or []),
        featured_at=row.get("featured_at") or "",
        created_at=row.get("created_at") or "",
    )


def get_run_dir(out_dir: Path, run_date: datetime) -> Path:
    """Return the date-named output folder for this run."""

    return out_dir / run_date.strftime("%Y-%m-%d")


def safe_filename_part(value: str) -> str:
    """Keep configurable prefixes safe for Windows file names."""

    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return normalized.strip("._") or DEFAULT_OUTPUT_PREFIX


def get_checkpoint_path(out_dir: Path, run_date: datetime, output_prefix: str) -> Path:
    """Return the checkpoint file path inside the date folder."""

    safe_prefix = safe_filename_part(output_prefix)
    checkpoint_name = CHECKPOINT_FILENAME
    if safe_prefix != DEFAULT_OUTPUT_PREFIX:
        checkpoint_name = f"checkpoint_{safe_prefix}.json"
    return get_run_dir(out_dir, run_date) / checkpoint_name


def get_output_paths(out_dir: Path, run_date: datetime, output_prefix: str) -> tuple[Path, Path]:
    """Return the stable date-level CSV and JSON output paths."""

    run_dir = get_run_dir(out_dir, run_date)
    date_suffix = run_date.strftime("%Y-%m-%d")
    safe_prefix = safe_filename_part(output_prefix)
    return (
        run_dir / f"{safe_prefix}_{date_suffix}.csv",
        run_dir / f"{safe_prefix}_{date_suffix}.json",
    )


def make_checkpoint_params(days: int, min_votes: int, topics: list[str]) -> dict[str, Any]:
    """Build the parameter fingerprint used to decide whether resume is safe."""

    return {
        "days": days,
        "min_votes": min_votes,
        "topics": sorted({slugify_topic(topic) for topic in topics if slugify_topic(topic)}),
    }


def new_checkpoint(params: dict[str, Any]) -> dict[str, Any]:
    """Create an empty checkpoint for a date folder."""

    topic_order = list(params["topics"])
    return {
        "version": 1,
        "params": params,
        "topic_order": topic_order,
        "current_topic_index": 0,
        "topic_cursors": {topic: None for topic in topic_order},
        "completed_topics": [],
        "products": [],
        "batch_target_count": None,
        "exhausted": False,
        "last_request": None,
        "updated_at": isoformat_z(utc_now()),
    }


def load_checkpoint(path: Path, params: dict[str, Any], resume: bool) -> dict[str, Any]:
    """Load a compatible checkpoint, or start a fresh one."""

    if not resume or not path.exists():
        checkpoint = new_checkpoint(params)
        if resume:
            seed_products_from_existing_output(checkpoint, path.parent)
        return checkpoint

    with path.open("r", encoding="utf-8") as checkpoint_file:
        checkpoint = json.load(checkpoint_file)

    # A checkpoint is only safe to reuse when the query-defining options match.
    # If the user changes topics/date window/min votes, start a new checkpoint.
    if checkpoint.get("params") != params:
        return new_checkpoint(params)

    return checkpoint


def seed_products_from_existing_output(checkpoint: dict[str, Any], run_dir: Path) -> None:
    """Seed a fresh checkpoint from today's JSON output if it already exists.

    This covers the case where the user has the dated output file but the
    checkpoint was deleted. Cursor state cannot be recovered from the output
    file, but product IDs can still be reused for deduplication.
    """

    date_suffix = run_dir.name
    json_path = run_dir / f"producthunt_products_{date_suffix}.json"
    if not json_path.exists():
        return

    try:
        with json_path.open("r", encoding="utf-8") as output_file:
            rows = json.load(output_file)
    except (OSError, json.JSONDecodeError):
        return

    products_by_id: dict[str, Product] = {}
    for row in rows:
        product = product_from_json_row(row)
        if product.id:
            products_by_id[product.id] = product
    sync_checkpoint_products(checkpoint, products_by_id)


def save_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    """Persist checkpoint data atomically enough for normal local use."""

    path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint["updated_at"] = isoformat_z(utc_now())
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as checkpoint_file:
        json.dump(checkpoint, checkpoint_file, ensure_ascii=False, indent=2)
        checkpoint_file.write("\n")
    tmp_path.replace(path)


def is_checkpoint_exhausted(path: Path) -> bool:
    """Return True when the checkpoint says all matching pages are finished."""

    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as checkpoint_file:
            checkpoint = json.load(checkpoint_file)
    except (OSError, json.JSONDecodeError):
        return False
    return bool(checkpoint.get("exhausted"))


def load_config(config_path: Path) -> dict[str, Any]:
    """Load project-level crawler settings from JSON."""

    config = dict(DEFAULT_CONFIG)
    if not config_path.exists():
        return config

    try:
        with config_path.open("r", encoding="utf-8") as config_file:
            file_config = json.load(config_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to read config file {config_path}: {exc}") from exc

    if not isinstance(file_config, dict):
        raise ValueError(f"Config file {config_path} must contain a JSON object.")

    for key in DEFAULT_CONFIG:
        if key in file_config:
            config[key] = file_config[key]
    return config


def merge_cli_overrides(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Apply explicit command-line overrides on top of config.json."""

    merged = dict(config)
    for key in ("days", "min_votes", "topics", "out_dir", "limit", "page_size", "timeout", "output_prefix"):
        value = getattr(args, key)
        if value is not None:
            merged[key] = value

    if args.comments_per_product is not None:
        merged["comments_per_product"] = args.comments_per_product
    if args.no_comments:
        merged["collect_comments"] = False
    if args.collect_comments:
        merged["collect_comments"] = True
    if args.wait_on_rate_limit:
        merged["wait_on_rate_limit"] = True
    if args.no_resume:
        merged["resume"] = False

    return normalize_config(merged)


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize config values before use."""

    normalized = dict(config)
    normalized["days"] = int(normalized["days"])
    normalized["min_votes"] = int(normalized["min_votes"])
    normalized["limit"] = int(normalized["limit"])
    normalized["page_size"] = int(normalized["page_size"])
    normalized["timeout"] = int(normalized["timeout"])
    normalized["comments_per_product"] = int(normalized["comments_per_product"])
    normalized["out_dir"] = Path(str(normalized["out_dir"]))
    normalized["output_prefix"] = safe_filename_part(str(normalized["output_prefix"]))
    normalized["wait_on_rate_limit"] = bool(normalized["wait_on_rate_limit"])
    normalized["collect_comments"] = bool(normalized["collect_comments"])
    normalized["resume"] = bool(normalized["resume"])

    topics = normalized["topics"]
    if isinstance(topics, str):
        topics = [topics]
    if not isinstance(topics, list) or not topics:
        raise ValueError("Config `topics` must be a non-empty list or string.")
    normalized["topics"] = [str(topic) for topic in topics]

    return normalized


def checkpoint_products(checkpoint: dict[str, Any]) -> dict[str, Product]:
    """Return checkpoint products keyed by Product Hunt ID for deduplication."""

    products: dict[str, Product] = {}
    for row in checkpoint.get("products", []):
        product = product_from_json_row(row)
        if product.id:
            products[product.id] = product
    return products


def sync_checkpoint_products(checkpoint: dict[str, Any], products_by_id: dict[str, Product]) -> None:
    """Write sorted product rows back into the checkpoint."""

    products = sorted(products_by_id.values(), key=lambda product: product.votes_count, reverse=True)
    checkpoint["products"] = [product_to_json_row(product) for product in products]


def write_outputs(
    products: list[Product],
    out_dir: Path,
    run_date: datetime,
    output_prefix: str,
) -> tuple[Path, Path]:
    """Write the accumulated products to stable date-level CSV and JSON files."""

    run_dir = get_run_dir(out_dir, run_date)
    run_dir.mkdir(parents=True, exist_ok=True)
    csv_path, json_path = get_output_paths(out_dir, run_date, output_prefix)

    csv_fields = [
        "name",
        "tagline",
        "description",
        "website_url",
        "producthunt_url",
        "votes_count",
        "comments_count",
        "comments_sample",
        "topics",
        "featured_at",
        "created_at",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=csv_fields)
        writer.writeheader()
        for product in products:
            row = product_to_json_row(product)

            # CSV is flat, so join topic names into a single readable cell.
            row["topics"] = "; ".join(product.topics)
            row["comments_sample"] = " || ".join(
                comment.get("body", "").replace("\r", " ").replace("\n", " ").strip()
                for comment in product.comments
                if comment.get("body")
            )
            writer.writerow({field: row[field] for field in csv_fields})

    # JSON keeps list fields intact for downstream scripts.
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump([product_to_json_row(product) for product in products], json_file, ensure_ascii=False, indent=2)
        json_file.write("\n")

    return csv_path, json_path


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface for manual and scheduled runs."""

    parser = argparse.ArgumentParser(
        description="Fetch recent Product Hunt products in Developer Tools or Productivity with high votes."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(CONFIG_FILENAME),
        help="Path to crawler config JSON. Default: config.json.",
    )
    parser.add_argument("--days", type=int, default=None, help="Override config lookback window in days.")
    parser.add_argument("--min-votes", type=int, default=None, help="Override config minimum vote threshold.")
    parser.add_argument(
        "--topics",
        nargs="+",
        default=None,
        help="Override config Product Hunt topic slugs or names.",
    )
    parser.add_argument("--out-dir", type=Path, default=None, help="Override config output directory.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override config maximum new products per run. Use 0 for no limit.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=None,
        help="Override config GraphQL page size, max 100.",
    )
    parser.add_argument("--timeout", type=int, default=None, help="Override config HTTP timeout in seconds.")
    parser.add_argument("--output-prefix", default=None, help="Override config output file prefix.")
    parser.add_argument("--comments-per-product", type=int, default=None, help="Override config comment sample size.")
    parser.add_argument("--collect-comments", action="store_true", help="Override config and collect comment samples.")
    parser.add_argument("--no-comments", action="store_true", help="Override config and skip comment collection.")
    parser.add_argument(
        "--wait-on-rate-limit",
        action="store_true",
        help="Override config and wait/retry when Product Hunt returns a rate limit.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Override config and ignore today's checkpoint.",
    )
    return parser


def main() -> int:
    """CLI entrypoint.

    Returns a process exit code instead of calling `sys.exit` directly, which
    keeps the function simple to test.
    """

    # Load a local .env file if present. Environment variables still work and
    # take precedence according to python-dotenv's default behavior.
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    try:
        config = merge_cli_overrides(load_config(args.config), args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    token = os.getenv("PRODUCTHUNT_ACCESS_TOKEN")
    if not token:
        # Missing credentials is a setup error, so return 2 like many CLIs do
        # for invalid/missing user input.
        print(
            "Missing PRODUCTHUNT_ACCESS_TOKEN. Create a Product Hunt developer token, then set it in your shell "
            "or put it in a local .env file.",
            file=sys.stderr,
        )
        return 2

    try:
        run_date = local_now()
        checkpoint_path = get_checkpoint_path(config["out_dir"], run_date, config["output_prefix"])

        # Collect data first, then write both output formats from the same
        # normalized in-memory result to keep CSV and JSON consistent.
        products = collect_products(
            token=token,
            days=config["days"],
            min_votes=config["min_votes"],
            topics=config["topics"],
            page_size=config["page_size"],
            timeout=config["timeout"],
            wait_on_rate_limit=config["wait_on_rate_limit"],
            limit=config["limit"],
            collect_comments=config["collect_comments"],
            comments_per_product=config["comments_per_product"],
            checkpoint_path=checkpoint_path,
            resume=config["resume"],
        )
        csv_path, json_path = write_outputs(
            products,
            config["out_dir"],
            run_date,
            config["output_prefix"],
        )
    except (ProductHuntError, ValueError, requests.RequestException) as exc:
        # Keep error output concise for scheduled runs and shell review.
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Print relative paths exactly as the script wrote them.
    print(f"Saved {len(products)} products")
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")
    print(f"Checkpoint: {checkpoint_path}")
    if is_checkpoint_exhausted(checkpoint_path):
        print("Status: all matching Product Hunt pages have already been scanned for today.")
    return 0


if __name__ == "__main__":
    # Convert the integer return code from main() into the process exit status.
    raise SystemExit(main())
