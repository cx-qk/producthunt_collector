# Product Hunt Collector

一个基于 Product Hunt 官方 GraphQL API 的本地采集工具，用来按话题、时间窗口和票数阈值收集近期高热产品，并输出适合后续分析的 CSV / JSON 数据。

当前默认配置会采集最近 30 天内 `developer-tools` 和 `productivity` 话题下票数大于 500 的产品。脚本支持断点续跑、去重、评论样本采集、CSV/JSON 双格式输出，以及 Windows/macOS 双击启动脚本。

## 功能特性

- 使用 Product Hunt 官方 GraphQL API，不做网页抓取。
- 按话题、最近天数、最低票数过滤产品。
- 默认每次最多新增 20 条产品，降低 Product Hunt API complexity / rate limit 风险。
- 自动保存当天 `checkpoint.json`，中断后再次运行会从断点继续。
- 按 Product Hunt 产品 ID 去重，重复运行不会重复写入同一产品。
- 输出 UTF-8 CSV 和结构化 JSON，方便表格查看和二次分析。
- 可选采集每个产品的高赞评论样本。
- 支持通过 `config.json` 配置常用采集规则，也支持 CLI 参数临时覆盖。

## 项目结构

```text
producthunt_collector/
├─ fetch_producthunt.py        # 主采集脚本
├─ config.json                 # 默认采集配置
├─ pyproject.toml              # Python 项目与依赖声明
├─ uv.lock                     # uv 锁文件
├─ run_collector.bat           # Windows 双击启动脚本
├─ run_collector.command       # macOS 双击启动脚本
├─ data/YYYY-MM-DD/            # 运行后生成的数据目录
│  ├─ producthunt_products_YYYY-MM-DD.csv
│  ├─ producthunt_products_YYYY-MM-DD.json
│  └─ checkpoint.json
└─ .agents/skills/             # 可选的本地趋势分析技能
```

`.env`、虚拟环境和生成的数据文件不应该提交到 GitHub。仓库已经通过 `.gitignore` 忽略 `.env`、`.venv/`、`__pycache__/`、CSV 和 JSON 输出。

## 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- Product Hunt developer access token

依赖只有两个：

- `requests`
- `python-dotenv`

## 获取 Product Hunt Token

到 Product Hunt 开发者后台创建 API token，然后在项目根目录创建 `.env` 文件：

```text
PRODUCTHUNT_ACCESS_TOKEN=your_real_token
```

不要把真实 token 提交到 GitHub。

## 安装

在项目目录执行：

```powershell
uv sync
```

这会根据 `pyproject.toml` 和 `uv.lock` 创建或更新本地虚拟环境。

## 快速运行

```powershell
uv run python fetch_producthunt.py
```

默认输出位置：

```text
data/YYYY-MM-DD/producthunt_products_YYYY-MM-DD.csv
data/YYYY-MM-DD/producthunt_products_YYYY-MM-DD.json
data/YYYY-MM-DD/checkpoint.json
```

运行成功后终端会显示保存的产品数量和输出文件路径。

## 双击运行

如果不想打开命令行，也可以在项目目录双击启动脚本：

- Windows: `run_collector.bat`
- macOS: `run_collector.command`

这两个脚本都会执行默认采集命令，并在结束后保留终端窗口，方便查看结果或错误信息。

## 配置说明

默认配置在 `config.json`：

```json
{
  "topics": ["developer-tools", "productivity"],
  "days": 30,
  "min_votes": 500,
  "limit": 20,
  "page_size": 20,
  "timeout": 30,
  "out_dir": "data",
  "output_prefix": "producthunt_products",
  "collect_comments": true,
  "comments_per_product": 5,
  "wait_on_rate_limit": false,
  "resume": true
}
```

常用字段：

- `topics`: Product Hunt 话题 slug 或名称。
- `days`: 从当前时间往前看的天数。
- `min_votes`: 最低票数阈值，脚本会保留票数高于该值的产品。
- `limit`: 单次运行最多新增产品数；设为 `0` 表示不限制。
- `page_size`: 每次 GraphQL 请求的分页大小，最大 100。建议保持较小，避免 complexity limit。
- `collect_comments`: 是否为产品采集评论样本。
- `comments_per_product`: 每个产品最多采集多少条高赞评论。
- `wait_on_rate_limit`: 遇到 rate limit 时是否等待后重试。
- `resume`: 是否启用当天 checkpoint 续跑。
- `output_prefix`: 输出文件名前缀。不同采集任务建议使用不同前缀，避免数据混在同一天目录里。

## CLI 参数

查看完整参数：

```powershell
uv run python fetch_producthunt.py --help
```

常用示例：

```powershell
uv run python fetch_producthunt.py --days 30 --min-votes 500 --topics developer-tools productivity
```

采集 AI 和 Marketing 话题，并单独保存为另一组输出：

```powershell
uv run python fetch_producthunt.py --topics artificial-intelligence marketing --output-prefix ph_ai_marketing
```

跳过评论采集：

```powershell
uv run python fetch_producthunt.py --no-comments
```

忽略今天已有 checkpoint，重新开始当前配置的采集：

```powershell
uv run python fetch_producthunt.py --no-resume
```

做更大的回填任务：

```powershell
uv run python fetch_producthunt.py --limit 0 --page-size 20 --wait-on-rate-limit
```

## 断点续跑机制

脚本默认会把当天进度保存到：

```text
data/YYYY-MM-DD/checkpoint.json
```

checkpoint 会记录：

- 当前采集参数。
- 已采集产品。
- 当前话题和分页 cursor。
- 已完成的话题。
- 今天是否已经扫描完所有匹配页面。

再次运行同一配置时，脚本会复用 checkpoint 继续采集。如果修改了影响查询结果的配置，例如 `topics`、`days` 或 `min_votes`，脚本会自动开启新的 checkpoint 状态。

## 输出字段

CSV 适合人工查看，JSON 适合二次处理。主要字段包括：

- `id`: Product Hunt 产品 ID。
- `name`: 产品名称。
- `tagline`: 一句话介绍。
- `description`: 产品描述。
- `website_url`: Product Hunt API 返回的官网跳转链接。
- `producthunt_url`: Product Hunt 页面链接。
- `votes_count`: 票数。
- `comments_count`: 评论数。
- `comments`: JSON 中保留的评论样本。
- `comments_sample`: CSV 中拼接后的评论样本。
- `topics`: 产品所属话题。
- `topic_slugs`: JSON 中保留的话题 slug。
- `featured_at`: Featured 时间。
- `created_at`: 创建时间。

## 可选：生成趋势分析报告

仓库里包含一个本地 agent skill：`producthunt-trend-analyzer`。它不会调用 Product Hunt API，只读取已经采集到的 JSON 数据，并生成用于产品机会分析的 Markdown 报告。

典型流程：

1. 先运行采集器，得到 `data/YYYY-MM-DD/producthunt_products_YYYY-MM-DD.json`。
2. 运行本地趋势预处理脚本，生成 `trend_prep_YYYY-MM-DD.json`。
3. 由 agent 基于原始 JSON 和预处理 JSON 写出 `producthunt_trend_report_YYYY-MM-DD.md`。

预处理脚本示例：

```powershell
uv run python .agents/skills/producthunt-trend-analyzer/scripts/prepare_trend_inputs.py --project-root . --date 2026-05-20
```

趋势报告属于分析产物，不是 `fetch_producthunt.py` 的默认输出。

## 开发与校验

当前项目还没有正式测试目录。修改脚本后至少运行：

```powershell
uv run python -m py_compile fetch_producthunt.py
uv run python fetch_producthunt.py --help
```

后续如果添加测试，建议放在：

```text
producthunt_collector/tests/
```

优先覆盖：

- 配置加载与 CLI 覆盖。
- checkpoint 续跑。
- 产品去重。
- 输出路径生成。
- rate limit 处理。
- 不依赖真实 Product Hunt API 的数据标准化逻辑。

## GitHub 提交前检查

提交前建议确认：

```powershell
git status
```

不要提交：

- `.env`
- `.venv/`
- `__pycache__/`
- 真实 token
- 不打算公开的采集数据

可以提交：

- `fetch_producthunt.py`
- `config.json`
- `pyproject.toml`
- `uv.lock`
- `run_collector.bat`
- `run_collector.command`
- `README.md`
- `.agents/skills/` 中你希望一起公开的本地分析技能

## 注意事项

Product Hunt API 有 rate limit 和 complexity 限制。建议保持较小的 `page_size` 和 `comments_per_product`，用 checkpoint 分批采集，而不是一次性拉取大量数据。

Product Hunt 要求 API 使用者保留对 Product Hunt 的归因和链接。输出数据中的 Product Hunt URL 应在后续展示或分析中保留。
