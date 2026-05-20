"""为 Product Hunt 趋势报告准备确定性统计输入。"""  # 说明脚本用途：先做可重复统计，再交给模型写报告。
from __future__ import annotations  # 启用较新的类型注解写法，兼容 Python 3.10+。
import argparse  # 导入 argparse，用来解析命令行参数。
import json  # 导入 json，用来读取产品数据和写出统计结果。
import re  # 导入 re，用来做简单分词和功能诉求匹配。
from collections import Counter  # 导入 Counter，用来统计词频和 topic 频率。
from datetime import datetime  # 导入 datetime，用来默认选择今天日期。
from pathlib import Path  # 导入 Path，用来跨平台拼接文件路径。
from find_producthunt_data import find_data_file  # 复用同目录脚本的数据文件定位逻辑。
STOPWORDS = {"the", "and", "for", "with", "that", "this", "you", "your", "from", "into", "are", "our", "not", "can", "all", "was", "but", "have", "has", "had", "its", "get", "use", "using", "more", "new"}  # 定义英文停用词，减少无意义词频。
POSITIVE_TERMS = {"fast", "easy", "simple", "powerful", "open", "source", "privacy", "local", "automate", "smart", "reliable", "secure", "personalized", "real-time", "instant"}  # 定义正面信号词表。
NEGATIVE_TERMS = {"missing", "hard", "slow", "complex", "bug", "bugs", "fail", "failure", "expensive", "manual", "stale", "noise", "blocked", "risk", "struggle"}  # 定义负面或痛点信号词表。
REQUEST_PATTERNS = [r"wish[^.。!?]*", r"would be better if[^.。!?]*", r"missing[^.。!?]*", r"needs?[^.。!?]*", r"要是有[^。!?]*", r"希望[^。!?]*"]  # 定义功能诉求常见表达。
def words(text: str) -> list[str]:  # 定义函数：把文本拆成适合粗略统计的词。
    """把文本转换成小写英文词列表。"""  # 说明函数输出。
    return [word for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text.lower()) if word not in STOPWORDS]  # 返回过滤停用词后的英文词。
def collect_text(product: dict) -> str:  # 定义函数：汇总一个产品可分析的全部文本。
    """合并产品标题、简介、描述、话题和评论文本。"""  # 说明函数用途。
    parts = [product.get("name", ""), product.get("tagline", ""), product.get("description", "")]  # 收集产品基础文本字段。
    parts.extend(product.get("topics") or [])  # 把 topic 名称也加入文本来源。
    parts.extend(comment.get("body", "") for comment in product.get("comments", []) if comment.get("body"))  # 加入评论正文。
    return " ".join(parts)  # 合并成一个字符串供分词和匹配使用。
def extract_requests(text: str) -> list[str]:  # 定义函数：从文本里抽取潜在功能诉求表达。
    """用简单模式匹配抽取功能诉求片段。"""  # 说明这是确定性粗抽取，不替代模型判断。
    snippets: list[str] = []  # 创建结果列表。
    for pattern in REQUEST_PATTERNS:  # 遍历每一种功能诉求模式。
        snippets.extend(match.group(0).strip() for match in re.finditer(pattern, text, flags=re.IGNORECASE))  # 收集所有匹配片段。
    return snippets[:20]  # 限制数量，避免统计文件过长。
def analyze(products: list[dict]) -> dict:  # 定义函数：对产品列表做确定性统计。
    """生成报告前可复用的结构化统计摘要。"""  # 说明函数返回结构化摘要。
    topic_counter: Counter[str] = Counter()  # 创建 topic 计数器。
    word_counter: Counter[str] = Counter()  # 创建通用词频计数器。
    positive_counter: Counter[str] = Counter()  # 创建正面词计数器。
    negative_counter: Counter[str] = Counter()  # 创建负面词计数器。
    request_snippets: list[dict] = []  # 创建功能诉求片段列表。
    product_summaries: list[dict] = []  # 创建产品摘要列表。
    for product in products:  # 遍历每个产品。
        text = collect_text(product)  # 汇总该产品的全部文本。
        tokens = words(text)  # 对文本做简单分词。
        topic_counter.update(product.get("topics") or [])  # 统计 topic 出现次数。
        word_counter.update(tokens)  # 统计词频。
        positive_counter.update(token for token in tokens if token in POSITIVE_TERMS)  # 统计正面词。
        negative_counter.update(token for token in tokens if token in NEGATIVE_TERMS)  # 统计负面词。
        snippets = extract_requests(text)  # 抽取该产品的功能诉求片段。
        for snippet in snippets:  # 遍历功能诉求片段。
            request_snippets.append({"product": product.get("name", ""), "snippet": snippet})  # 保存片段及对应产品名。
        product_summaries.append({"name": product.get("name", ""), "votes_count": product.get("votes_count", 0), "comments_count": product.get("comments_count", 0), "topics": product.get("topics", []), "tagline": product.get("tagline", "")})  # 保存报告常用的产品摘要。
    return {"product_count": len(products), "products": product_summaries, "top_topics": topic_counter.most_common(20), "top_words": word_counter.most_common(30), "positive_terms": positive_counter.most_common(20), "negative_terms": negative_counter.most_common(20), "feature_request_snippets": request_snippets[:50], "has_comment_bodies": any(product.get("comments") for product in products)}  # 返回完整统计结果。
def build_parser() -> argparse.ArgumentParser:  # 定义函数：创建命令行参数解析器。
    """创建命令行参数解析器。"""  # 说明函数职责。
    parser = argparse.ArgumentParser(description="为 Product Hunt 趋势报告生成预分析 JSON。")  # 创建解析器并写中文说明。
    parser.add_argument("--project-root", type=Path, default=Path.cwd(), help="仓库根目录或 producthunt_collector 目录。")  # 添加项目根目录参数。
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="要分析的日期，格式为 YYYY-MM-DD。")  # 添加日期参数，默认今天。
    return parser  # 返回解析器。
def main() -> int:  # 定义脚本入口函数。
    """读取当天产品 JSON，输出预分析 JSON 文件。"""  # 说明入口函数行为。
    args = build_parser().parse_args()  # 解析命令行参数。
    data_file = find_data_file(args.project_root.resolve(), args.date)  # 定位指定日期的数据文件。
    if not data_file:  # 如果数据文件不存在。
        print(f"missing:{args.date}")  # 打印缺失信息。
        return 1  # 返回失败状态码。
    products = json.loads(data_file.read_text(encoding="utf-8"))  # 读取产品 JSON 数据。
    summary = analyze(products)  # 生成确定性统计摘要。
    output_path = data_file.parent / f"trend_prep_{args.date}.json"  # 拼出预分析输出路径。
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")  # 写出 UTF-8 JSON 文件。
    print(output_path)  # 打印输出文件路径。
    return 0  # 返回成功状态码。
if __name__ == "__main__":  # 判断当前文件是否作为脚本直接运行。
    raise SystemExit(main())  # 调用 main，并把返回值作为进程退出码。
