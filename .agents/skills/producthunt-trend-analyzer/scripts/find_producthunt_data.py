"""定位指定日期的 Product Hunt 采集结果 JSON 文件。"""  # 说明脚本用途：只查找本地数据文件，不请求 Product Hunt API。
from __future__ import annotations  # 启用较新的类型注解写法，兼容 Python 3.10+。
import argparse  # 导入 argparse，用来解析命令行参数。
import json  # 导入 json，用来读取 config.json 配置文件。
from datetime import datetime  # 导入 datetime，用来生成默认的今天日期。
from pathlib import Path  # 导入 Path，用来安全拼接 Windows 和 macOS 都能使用的路径。
DEFAULT_OUTPUT_PREFIX = "producthunt_products"  # 定义默认输出文件前缀，和采集器默认配置保持一致。
def resolve_collector_dir(project_root: Path) -> Path:  # 定义函数：把输入路径解析成 producthunt_collector 目录。
    """兼容传入仓库根目录或直接传入 producthunt_collector 目录。"""  # 说明函数支持两种常见调用方式。
    if (project_root / "config.json").exists() and (project_root / "fetch_producthunt.py").exists():  # 如果当前路径已经是采集器目录。
        return project_root  # 直接返回当前路径，避免重复拼接 producthunt_collector。
    return project_root / "producthunt_collector"  # 否则把输入路径当作外层仓库根目录，再拼出采集器目录。
def load_output_prefix(collector_dir: Path) -> str:  # 定义函数：从采集器目录读取 output_prefix。
    """读取 config.json 中的 output_prefix；读取失败时返回默认前缀。"""  # 说明函数的容错行为。
    config_path = collector_dir / "config.json"  # 拼出采集器配置文件 config.json 的路径。
    if not config_path.exists():  # 如果配置文件不存在，就无法读取自定义前缀。
        return DEFAULT_OUTPUT_PREFIX  # 返回默认前缀，确保脚本仍然可用。
    try:  # 尝试读取和解析 JSON 配置。
        with config_path.open("r", encoding="utf-8") as config_file:  # 用 UTF-8 打开配置文件，避免中文或特殊字符乱码。
            config = json.load(config_file)  # 把 config.json 解析成 Python 字典。
    except (OSError, json.JSONDecodeError):  # 如果文件读取失败或 JSON 格式错误，就走兜底逻辑。
        return DEFAULT_OUTPUT_PREFIX  # 返回默认前缀，避免脚本因为配置损坏直接崩溃。
    return str(config.get("output_prefix") or DEFAULT_OUTPUT_PREFIX)  # 返回配置里的前缀；如果为空则返回默认前缀。
def find_data_file(project_root: Path, date_text: str) -> Path | None:  # 定义函数：按项目根目录和日期查找数据文件。
    """根据项目根目录和日期，返回对应的 Product Hunt JSON 文件路径。"""  # 说明函数输入和输出。
    collector_dir = resolve_collector_dir(project_root)  # 解析出真正的 producthunt_collector 目录。
    output_prefix = load_output_prefix(collector_dir)  # 读取当前配置使用的输出文件前缀。
    data_path = collector_dir / "data" / date_text / f"{output_prefix}_{date_text}.json"  # 拼出当天 JSON 文件路径。
    if data_path.exists():  # 如果文件存在，说明这一天有可分析数据。
        return data_path  # 返回找到的 JSON 文件路径。
    return None  # 如果文件不存在，返回 None 让调用方处理缺失情况。
def build_parser() -> argparse.ArgumentParser:  # 定义函数：构造命令行参数解析器。
    """创建命令行参数解析器。"""  # 说明函数职责。
    parser = argparse.ArgumentParser(description="定位某一天的 Product Hunt 采集结果 JSON 文件。")  # 创建解析器并写中文说明。
    parser.add_argument("--project-root", type=Path, default=Path.cwd(), help="仓库根目录，默认是当前目录。")  # 添加项目根目录参数。
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="要查找的日期，格式为 YYYY-MM-DD。")  # 添加日期参数，默认今天。
    return parser  # 返回配置好的解析器。
def main() -> int:  # 定义脚本入口函数，并用整数返回进程状态码。
    """脚本入口：打印找到的文件路径，找不到时返回非零状态码。"""  # 说明入口函数行为。
    parser = build_parser()  # 创建命令行参数解析器。
    args = parser.parse_args()  # 解析用户传入的命令行参数。
    data_file = find_data_file(args.project_root.resolve(), args.date)  # 查找指定日期的数据文件。
    if not data_file:  # 如果没有找到数据文件。
        print(f"missing:{args.date}")  # 打印缺失标记，方便上层工具识别。
        return 1  # 返回 1，表示没有找到文件。
    print(data_file)  # 打印找到的 JSON 文件完整路径。
    return 0  # 返回 0，表示成功找到文件。
if __name__ == "__main__":  # 判断当前文件是否作为脚本直接运行。
    raise SystemExit(main())  # 调用 main，并把返回值作为进程退出码。
