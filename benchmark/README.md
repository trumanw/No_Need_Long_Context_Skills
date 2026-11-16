# Token 对照实验

用 Cursor SDK 在同一个合成项目上对比两种条件，记录 SDK 报告的 token 用量和答案正确率，并按 Cursor 标价换算成美元。

- **baseline**：项目只有一份普通的 `AGENTS.md`（项目说明和目录）。
- **context-state**：在 baseline 的基础上加 context-state 规则块、Skill、stop 钩子，以及由同一模型一次引导运行写出的 `STATE.md` 和 `LEDGER.md`。引导运行的费用单独记为一次性成本。

两种条件的项目文件除上述内容外逐字节相同（`tests/test_benchmark.py` 有检查）。每次运行都是新项目副本里的一个新对话；只加载项目级设置（`setting_sources=["project"]`），不加载本机的用户规则和插件。

## 合成项目

`fixture.py` 生成一个跑了两天的催化剂筛选研究：三条工作线、计划和报告、作业日志、一个作业队列和提交脚本。要回答的事实分散在长报告中段和日志里，计划和后来的报告之间有一处矛盾（泛函从 PBE 改为 RPBE）。`advance` 模拟过一天：运行中的作业完成，只有 agent 前一天真的提交了重算，重算结果才会出现。

`--scales` 控制项目规模，事实不变，只增加报告段落、日志长度和旧笔记：

| 规模 | 文件数 | 字符数 |
|---|---|---|
| x1 | 17 | 约 119K |
| x3 | 23 | 约 355K |
| x6 | 32 | 约 748K |

## 任务

| 套件 | 任务 | 判分 |
|---|---|---|
| `resume` | R1 现状与下一步，R2 泛函及原因，R3 代理模型选择与待解决问题，R4 失败及处理 | 答案中的关键事实（正则） |
| `multiday` | 连续四天，每天一个新对话："Continue the dft-screen work."，第四天要求写 `FINAL.md` | 答案事实加磁盘检查（是否带正确参数提交了重算、生成了 `volcano.json`、写了 `FINAL.md`） |

## 运行

```bash
python3 -m venv .venv && .venv/bin/pip install -r benchmark/requirements.txt
export CURSOR_API_KEY=...                      # Cursor Dashboard → Integrations
.venv/bin/python benchmark/run.py --list-models --models grok-4.7 composer-2.5
.venv/bin/python benchmark/run.py --probe --models "composer-2.5:fast=false"

.venv/bin/python benchmark/run.py --suite resume --suite multiday \
    --models "grok-4.7:context=256k,reasoning_effort=high,fast=false" "composer-2.5:fast=false" \
    --scales 1 3 6 --reps 3 --out benchmark/results/raw.jsonl

.venv/bin/python benchmark/report.py benchmark/results/raw.jsonl
```

- 模型要写全参数（`--list-models` 列出可选值）。不写时 SDK 用默认档位，价格可能是 Fast 档；每条记录都保存了实际使用的模型和参数（`model_resolved`）。
- `--probe` 让模型读一个文件里的暗号，确认工具调用正常。只回答"OK"不算通过。
- 已完成的记录自动跳过，中断后重跑同一条命令即可续跑；连续 2 次出错会中止。
- `report.py` 写出 `results/summary.md` 和 `results/figures/*.png`。

## 隔离

agent 能读任意绝对路径，所以只靠"工作目录"不能防止它看到答案。目前的做法：

- 项目里没有提示它处在测试中的文字或路径；钩子脚本复制进项目，用相对路径调用。
- 运行副本放在仓库外（默认 `/tmp/cs-lab`），一次只有一个副本，路径不透露条件；其余副本放在权限为 000 的目录里。
- 每次运行后删除该副本在 `~/.cursor/projects/` 下的对话记录。
- 记录 agent 读过的工作目录以外的路径（`outside_paths`），报告会排除这些运行。

## 价格

`prices.json` 抄自 [Cursor 模型与价格](https://cursor.com/docs/models-and-pricing)（2026-11-15），单位为每百万 token 的美元价格。费用 = 未缓存输入 × 输入价 + 缓存读取 × 缓存读取价 + 输出 × 输出价；这两个模型没有单独的缓存写入价，按输入价计。价格表里找不到档位的运行，改用相对权重（`--prices`），并在表中标 `*`。Composer 2.5 和 Grok 4.7 在付费计划里先用每周额度，实际扣费可能低于标价。

## 解读时注意

- token 数是 SDK 运行时报告的值；IDE 内的系统提示和工具集不同，绝对值会有差别，比例更有参考意义。
- 每个任务只重复 3 次，单个任务的波动可达 ±50%；看套件合计和规模趋势，不要看单次运行。
- 方法本身是在 Grok 4.7、x1 的小试跑中修正的：修掉了反复修剪 STATE、日常接手也去读 Skill 等问题（见 `CHANGELOG.md` 0.2.1）。修正后方法冻结，正式数据全部用冻结后的版本，项目副本也按 Skill 文件的哈希重新生成。
- 只测了 Grok 4.7 和 Composer 2.5。Claude、GPT、Gemini 在测试所在地区通过 SDK 不可用；Kimi K3 通过 SDK 时不能正常调用工具。
- 合成项目最大约 748K 字符，仍小于很多真实的长期项目；资料越多，baseline 读得越多，差距通常越大。
