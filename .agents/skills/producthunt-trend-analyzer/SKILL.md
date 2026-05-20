---
name: producthunt-trend-analyzer
description: Manually analyze locally collected producthunt_collector Product Hunt data and produce two dated Markdown reports: a concrete product/site catalog explaining what each product does, and a separate conclusion report with sharp trend, opportunity, and gap judgments. Use only when the user explicitly invokes this skill or clearly asks to analyze existing Product Hunt collector output; do not trigger automatically while collecting data, configuring the crawler, or chatting generally.
---

# Product Hunt 趋势分析器

这个技能用于分析 `producthunt_collector` 已经爬取到本地的 Product Hunt 数据。它不调用 Product Hunt API，也不启动爬虫，只读取本地 JSON 输出，并最终生成两份 Markdown 报告文件：

1. 产品/网站清单报告：逐个列出这些产品分别是做什么的。
2. 趋势结论报告：只写更明确的趋势、机会、缺口和取舍判断。

## 触发规则

只有在用户明确手动调用时才使用本技能，例如：

- `$producthunt-trend-analyzer 分析今天的数据`
- `用 Product Hunt 趋势分析器分析 2026-05-20`
- `把爬下来的 Product Hunt 数据总结一下趋势`

如果用户只是要采集数据、修改爬虫配置、运行启动脚本，不要使用本技能。

## 日期选择

默认分析本地时间的今天。默认查找路径：

`producthunt_collector/data/YYYY-MM-DD/`

如果今天没有数据文件，并且用户没有指定日期，必须停下来提示用户指定日期或先运行采集器。不要自动切换到其它日期。

如果用户指定了日期，只分析那个日期的数据。

## 数据读取

优先读取 JSON，不优先读取 CSV。默认文件名是：

`producthunt_products_YYYY-MM-DD.json`

如果 `config.json` 配置了自定义 `output_prefix`，则读取：

`<output_prefix>_YYYY-MM-DD.json`

可以用辅助脚本定位文件：

```bash
python scripts/find_producthunt_data.py --project-root <repo-root> --date YYYY-MM-DD
```

`--project-root` 可以传外层仓库目录，也可以直接传 `producthunt_collector` 目录。

## 多任务隔离

如果用户要分析不同主题或不同过滤规则，先检查 `config.json` 的 `output_prefix`。不同任务应该使用不同 `output_prefix`，否则不同主题的数据、checkpoint 和报告会混在同一个日期目录里。

示例：

- DevTools/Productivity：`producthunt_products`
- AI/Marketing：`ph_ai_marketing`
- SaaS/Payments：`ph_saas_payments`

## 预分析脚本

写报告前，先运行确定性预分析脚本：

```bash
python scripts/prepare_trend_inputs.py --project-root <repo-root> --date YYYY-MM-DD
```

这个脚本会生成：

`producthunt_collector/data/YYYY-MM-DD/trend_prep_YYYY-MM-DD.json`

报告应同时参考原始产品 JSON 和这个预分析 JSON。预分析 JSON 用来提供产品数、产品摘要、topic 分布、词频、正面词、负面词、功能诉求片段和是否存在评论正文等基础证据。

## 分析要求

读取产品记录后，输出两类内容，但必须拆成两个文件，不要混成一份大报告。

第一份报告回答“有哪些产品/网站，它们分别做什么”：

1. 每个产品一行或一小节，不要写成抽象趋势。
2. 必须包含产品名称、产品链接、票数、评论数、话题、面向对象、核心功能、解决的问题、可能的使用场景。
3. 产品链接使用原始 JSON 的 `website_url` 字段，让用户可以直接点击打开；不要在清单报告里展示 `producthunt_url`。
4. 只根据本地 JSON 的 `name`、`tagline`、`description`、`topics`、`votes_count`、`comments_count`、`website_url` 和评论样本判断，不要补查官网，不要编造没出现的功能。

第二份报告回答“我能从这些产品里得出什么结论”：

1. 这些产品主要在解决什么明确问题。
2. 明显的需求分组或产品类别。
3. 值得关注的产品机会，必须写成具体可执行方向。
4. 正面高频词或高频短语代表什么需求，不要只罗列词频。
5. 负面高频词或高频短语代表什么风险，不要只罗列词频。
6. 功能诉求和缺口，特别关注类似“wish it had X”“would be better if”“missing”“needs”“要是有 XX 功能就好了”的表达。
7. 明确写出“可以做什么”“不建议做什么”“为什么现在有机会”，避免泛泛地说 AI、效率、自动化。

采集器现在会尽量为每个产品抓取少量高赞评论。如果数据里没有评论，必须明确说明，并基于 `tagline`、`description`、`topics` 等已有字段做文本分析。不要编造用户评论。

## 报告格式

最终产物必须是两份报告文件，而不是只在对话里回答。默认把报告写到对应日期目录：

1. `producthunt_collector/data/YYYY-MM-DD/producthunt_site_catalog_YYYY-MM-DD.md`
2. `producthunt_collector/data/YYYY-MM-DD/producthunt_trend_conclusions_YYYY-MM-DD.md`

如果同名报告已经存在，可以覆盖更新，因为报告应该反映当前日期文件里的最新累计数据。

对话回复中只需要简短说明两个报告路径和 3-5 条最重要结论。

产品/网站清单报告必须使用中文撰写，并始终使用这个结构：

```markdown
# Product Hunt 产品/网站清单 - YYYY-MM-DD

## 数据范围
## 产品总览表
<!-- 表格至少包含：编号、产品名、产品链接、票数、评论数、话题、它是做什么的、面向对象。产品链接用 website_url，不要展示 producthunt_url。 -->
## 逐个产品说明
<!-- 每个产品用 4-6 句说清楚核心功能、解决的问题、使用场景、从评论中看到的线索，并在标题下单独放一行“产品链接：<website_url>”。 -->
## 备注与限制
```

趋势结论报告必须使用中文撰写，并始终使用这个结构：

```markdown
# Product Hunt 趋势结论 - YYYY-MM-DD

## 结论摘要
<!-- 直接列 5-8 条判断，每条要具体，避免空泛。 -->
## 需求分组与证据
## 可以做的产品机会
## 不建议做的方向
## 正面信号
## 负面信号
## 功能诉求与缺口
## 备注与限制
```

报告要实用，所有判断尽量关联到具体产品名称、重复出现的表达、评论样本或票数/评论数信号。

趋势结论报告不要展示产品链接，避免结论报告变成长表格。

如果没有评论字段，把“正面信号”和“负面信号”明确标注为“基于标题、简介、描述和话题字段”，不要写成“用户评论显示”。

## 缺失数据处理

如果指定日期的数据文件不存在，回复：

```text
我没有看到 YYYY-MM-DD 的 Product Hunt 数据。请先运行采集器，或指定另一个日期让我分析。
```

除非用户明确同意，不要回退到其它日期。
