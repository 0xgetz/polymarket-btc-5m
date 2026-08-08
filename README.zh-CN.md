<div align="center">

<img src="assets/logo.png" alt="PolyBTC Momentum" width="200"/>

# PolyBTC Momentum

**开源 OpenClaw 技能：在 Polymarket 上进行 BTC 5 分钟涨跌动量交易**

[![CI](https://github.com/0xgetz/polymarket-btc-5m/actions/workflows/ci.yml/badge.svg)](https://github.com/0xgetz/polymarket-btc-5m/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Shell](https://img.shields.io/badge/shell-bash-green)
![Platform](https://img.shields.io/badge/platform-OpenClaw-black)
![Market](https://img.shields.io/badge/market-Polymarket%20BTC%205m-6f42c1)
![Strategy](https://img.shields.io/badge/strategy-momentum--into--close-orange)
![License](https://img.shields.io/badge/license-MIT-blue)

[**English**](README.md) · [**Bahasa Indonesia**](README.id.md) · [**简体中文**](README.zh-CN.md)

</div>

---

## 目录

- [演示](#-演示)
- [策略：收盘动量](#-策略收盘动量)
- [交易配置（Profile）](#-交易配置profile)
- [现实的预期](#-现实的预期)
- [仓库结构](#-仓库结构)
- [快速开始](#-快速开始)
- [用法](#-用法)
- [实盘安全（审计后）](#-实盘安全审计后)
- [工具与验证](#-工具与验证)
- [测试与 CI](#测试与-ci)
- [执行检查清单](#-执行检查清单)
- [风险控制](#-风险控制)
- [风险声明](#-风险声明)
- [支持与贡献](#-支持与贡献)

---

## 🎬 演示

### 实盘交易会话（conservative 配置）

<p align="center">
  <img src="assets/demo-trading.gif" alt="PolyBTC Momentum 实盘交易会话" width="820"/>
</p>

> 结算 BTC 5m 市场 → 确认动量 + 市场倾斜 + 优势 → 顺势入场 → 收盘前受控离场。

### 状态与盈亏报告

<p align="center">
  <img src="assets/demo-report.gif" alt="PolyBTC Momentum 状态与盈亏报告" width="820"/>
</p>

---

## 🎯 策略：收盘动量

这是一个短周期的**收盘动量**（momentum-into-close）策略组合——**不是**反转系统：

1. **交易**临近到期的 Polymarket BTC 5m 涨跌市场。
2. **入场时机**约为**剩余约 120 秒**（容差 / 硬性窗口均可配置）。
3. **动量确认**——要求当前 5 分钟 K 线有**带方向的** BTC 波动（`收盘 − 开盘`），可选**1 分钟 K 线一致性确认**（防插针）。
4. **市场倾斜**——跟随市场：CLOB 卖一价超过阈值；可选 `min_skew_gap` 与 `max_entry_price`。
5. **优势门槛**——要求 `预估胜率 − 入场价 ≥ min_edge`；可选 UTC **时段过滤**。
6. **仓位**——固定或**按优势缩放**的下注额（受配置上限约束），可选**连亏时逐步减仓**。
7. **离场**——CLOB 买一价硬止损，接近确定时**持有到结算**，浮亏或 BTC 临近到期反向时**提前砍仓**，否则按时离场。
8. **对冲**——临近收盘出现极端倾斜（如 95/5）时可选微型对冲。

所有配置参数**仅**存在于 `config/polybtc_profiles.yaml`。

---

## 📊 交易配置（Profile）

| 配置 | 用途 |
|---|---|
| `conservative` | 默认实盘路径：过滤更严、优势门槛、时段限制、按优势缩放仓位 |
| `aggressive` | 更高频率 / 风险，更宽松的优势与时段 |
| `high_confidence` | 精选中高价位区间、更强的动量要求、更多确认轮询 |
| `micro_10` | **小额实盘测试** — 约 10 USDT 本金，**每笔 $1**，每日最多 5 笔 |
| `observe` | **仅研究** — 为 `polybtc_live_logger` / 模拟盘提供宽松门槛；**不可用于实盘资金** |

### 约 10 USDT 的微额测试

使用 `micro_10` 配置，并将 equity 设为你真实的账户余额，使每日亏损百分比有意义：

```bash
# 1) 先模拟盘（不下单）
export POLYBTC_EQUITY=10
python scripts/test_polybtc_session_exit_sl.py --profile micro_10

# 或通过 ctl：
scripts/polybtc_ctl.sh start --profile micro_10

# 2) 仅在模拟盘看起来正常之后——真实 $1 订单（钱包需持有约 10 USDT）：
export POLYBTC_EQUITY=10
scripts/polybtc_ctl.sh start --profile micro_10 --live
# 等价于：
python scripts/test_polybtc_session_exit_sl.py --profile micro_10 --equity 10 --execute
```

`micro_10` 上限：单笔下注 **$1**、最大名义金额 **$1**、每日最多 **5** 笔、连续 **2** 次亏损后停止、每日最大亏损 **本金的 20%**（equity=10 时约 $2）。对冲禁用。你仍可能在数天内亏光全部本金。

---

## 📈 现实的预期

> **不保证盈利。** 这是一个高波动的投机策略。**没有任何设置能保证盈利**，任何承诺"99% 胜率"的说法都是在误导你。收益是不对称的——你以价格 `p` 买入某一方，所以你的**盈亏平衡胜率等于 `p`**：你必须正确 *超过* `p`% 的次数才能避免亏损。

| 入场价 | 获胜收益（$5 下注） | 亏损 | 盈亏平衡胜率 |
|---|---|---|---|
| 0.71 | +$2.04 | −$5.00 | **> 71%** |
| 0.90 | +$0.56 | −$5.00 | **> 90%** |
| 0.95 | +$0.26 | −$5.00 | **> 95%** |

在 0.71 价位，一次亏损会抵消约 2.4 次盈利。现实的目标是**可度量的正优势配合严格的资金保护**——而非必胜。在放大仓位之前，请使用分析、优势、离场和成交工具（见[工具与验证](#-工具与验证)）验证真实期望值。

---

## 🗂 仓库结构

| 路径 | 用途 |
|---|---|
| `SKILL.md` | 技能定义与操作规则 |
| `CONTOUR.md` | 规范执行路径 + 审计后安全说明 |
| `BACKTESTING.md` | CSV 历史回测 + 校准器指南 |
| `config/polybtc_profiles.yaml` | 配置 / 风险的唯一事实来源 |
| `scripts/` | 运行器、预检、分析、实盘记录器、报告（`_psr_impl.py` 为实盘会话实现） |
| `examples/` | 命令示例 + 示例回测 CSV |
| `assets/` | Logo 与演示 GIF |
| `tests/` | pytest（配置、预检、优势、风控、分析、模拟盘、汇总、实盘安全、回测、校准、离场/成交报告、记录器 CSV） |
| `.github/workflows/` | CI（lint、编译、配置校验、测试） |

---

## 🚀 快速开始

### 前置条件

- OpenClaw 环境（纯 Python 工具可选）
- 用于**真实订单**的 Polymarket 执行栈（如 `pm-hl-conservative-plus-repo`）
- Python 3.12+ venv：`pip install -r requirements.txt`（CLOB 客户端另需 `requirements-live.txt`）
- API 凭据仅放在仓库之外（通过环境变量 / 外部 `.env`）

### 快速上手

```bash
git clone https://github.com/0xgetz/polymarket-btc-5m.git
cd polymarket-btc-5m
pip install -r requirements.txt
```

然后阅读：

- `SKILL.md`
- `config/polybtc_profiles.yaml`

---

## 💻 用法

### 仅观察（不下单——很好的第一步）

```bash
python scripts/polybtc_live_logger.py --profile observe --minutes 60 --poll-sec 5
# JSONL + CSV 输出到 ./runtime/
```

### 模拟盘会话运行器（默认——不下单）

```bash
python scripts/test_polybtc_session_exit_sl.py --profile conservative
# 或：
scripts/polybtc_ctl.sh start --profile conservative
scripts/polybtc_ctl.sh start --profile high_confidence   # 精选
```

### 实盘——仅在验证之后（必须显式加参数）

```bash
python scripts/test_polybtc_session_exit_sl.py --profile conservative --execute
scripts/polybtc_ctl.sh start --profile conservative --live
```

### 统一技能控制

```bash
scripts/polybtc_ctl.sh start --profile conservative          # 模拟盘
scripts/polybtc_ctl.sh start --profile conservative --live   # 真实订单
scripts/polybtc_ctl.sh status
scripts/polybtc_ctl.sh report --limit 20
scripts/polybtc_ctl.sh stop   # 先 SIGTERM；若在交易中途被终止可能留下未平仓头寸
```

### 可选 Docker

```bash
scripts/polybtc_docker.sh up
scripts/polybtc_docker.sh status
scripts/polybtc_docker.sh down
```

---

## 🛡 实盘安全（审计后）

默认设置让真金白银难以被误触发：

| 控制项 | 行为 |
|---|---|
| **默认模式** | 模拟盘（不下单）。实盘需要 `--execute` / `polybtc_ctl.sh --live`。 |
| **预检门槛** | 时间、**带方向的** BTC 5m 动量（+ 上限）、可选 **1m 一致性**、报价时效、点差、流动性、阈值 / `max_entry`、倾斜差、多次轮询确认、**期望值门槛**、**时段**——任何开仓之前。 |
| **仓位** | 基础下注 + 可选**优势缩放** + **连亏软缩放**，硬性 `max_notional_usd`。 |
| **资金护栏** | 连亏熔断、每日最大亏损 %、每日最大交易数。 |
| **配置来源** | 仅 `config/polybtc_profiles.yaml`（`polybtc_config`）。 |
| **受控离场** | CLOB 买一价止损；接近确定时持有到结算；提前砍仓；按时离场（`decide_exit`）。 |
| **平仓限价下限** | 强制/GTC 平仓不得低于 `entry * (1 - max_close_slippage)`。 |
| **开仓环境变量** | 点差 / 卖一档名义金额来自配置（`PM_MAX_SPREAD`、`PM_MIN_TOP_ASK_NOTIONAL_USD`）。 |
| **停止语义** | `polybtc_ctl.sh stop`：SIGTERM → 等待 → SIGKILL；锁文件 + 未平仓头寸警告。 |
| **监视器** | `watch_polybtc_threshold_and_enter.sh` 默认模拟盘；锁文件；触发护栏即停止。 |

辅助：`scripts/polybtc_live_safety.py`（有单元测试）。实盘 CLOB 依赖：`requirements-live.txt`。

运行时隔离：

- 技能运行时目录：`./runtime`
- 认证/环境来源（默认）：`<your-workspace>/pm-hl-conservative-plus-repo/.env`
- 覆盖项：`POLYBTC_REPO`、`POLYBTC_ENV_FILE`、`POLYBTC_RUNNER`、`POLYBTC_RUNTIME_DIR`、`POLYBTC_PY`

---

## 🧪 工具与验证

大多数辅助工具是纯 / 确定性的（或仅通过公开 API 观察）。在实盘放量之前优先使用它们。

### 配置校验器

```bash
pip install -r requirements.txt
python scripts/polybtc_config.py --validate
python scripts/polybtc_config.py --profile conservative --show
python scripts/polybtc_config.py --profile observe --show
```

### 预检门槛

GO / NO-GO 引擎：方向、仓位（按优势 + 连亏缩放）、止损、对冲计划、检查项、优势。

```bash
python scripts/polybtc_preflight.py --profile conservative \
  --seconds-left 118 --btc-move-usd 110 --btc-move-1m-usd 12 \
  --up-ask 0.74 --dn-ask 0.28 --spread 0.02 --top-ask-notional 50 \
  --hour-utc 14
```

GO 示例（结构；数值取决于配置）：

```json
{
  "ok": true,
  "side": "UP",
  "entry_price": 0.74,
  "stake_usd": 6.25,
  "edge": 0.08,
  "estimated_win_prob": 0.82,
  "stake_scale": 1.25,
  "streak_scale": 1.0,
  "checks": {
    "session_hour": true,
    "time_to_close": true,
    "impulse_move": true,
    "impulse_max": true,
    "quote_fresh": true,
    "spread": true,
    "liquidity": true,
    "threshold_side": true,
    "move_aligned": true,
    "move_1m_aligned": true,
    "skew_confirm": true,
    "ev_gate": true
  }
}
```

### 实盘观察记录器 + CSV 导出（不下单）

```bash
python scripts/polybtc_live_logger.py --profile observe --minutes 60 --poll-sec 5
python scripts/polybtc_live_logger.py --export-jsonl runtime/polybtc_live_obs_....jsonl
```

### 精度校准器（CSV 网格搜索）

```bash
python scripts/polybtc_calibrate.py \
  --csv examples/polybtc_backtest_sample_data.csv \
  --profile conservative --top 10 --min-trades 2
```

详情：`BACKTESTING.md`。

### 回测（CSV 通过预检逻辑回放）

```bash
python scripts/polybtc_backtest.py \
  --csv examples/polybtc_backtest_sample_data.csv \
  --profile conservative
```

### 模拟/实盘后的报告

```bash
python scripts/polybtc_analytics.py --runtime-dir ./runtime --limit 200
python scripts/polybtc_exit_report.py --runtime-dir ./runtime --limit 200
python scripts/polybtc_fill_report.py --runtime-dir ./runtime --limit 200
python scripts/polybtc_daily_summary.py --profile conservative --equity 200
```

### 风控 / 优势计算 / 模拟盘

```bash
python scripts/polybtc_guardrails.py --profile conservative \
  --equity 200 --pnls=-5,-5,-5 --entry 0.71 --win-prob 0.80
python scripts/polybtc_edge.py --entry 0.71 --win-prob 0.80 --stake 5
python scripts/polybtc_edge.py --table
python scripts/polybtc_dryrun.py --profile conservative \
  --seconds-left 118 --btc-move-usd 84 --btc-move-1m-usd 10 \
  --up-ask 0.71 --dn-ask 0.29 --spread 0.02 --top-ask-notional 41 \
  --hour-utc 14 --market-slug btc-updown-5m-demo --outcome UP
```

### 测试与 CI

```bash
pip install -r requirements-dev.txt
pytest -q
```

CI 运行 bash/Python 语法检查、配置校验和完整测试套件。

---

## ✅ 执行检查清单

> 实盘交易前执行。

1. **市场有效性**——BTC 5m 时段活跃且未收盘。
2. **时间窗口**——足够的 `min_entry_seconds_left`；优选约 120 秒的目标窗口。
3. **动量**——5m 带方向波动 ≥ `btc_move_usd_min`，若设置了 ≤ `btc_move_usd_max`；方向一致。
4. **1m 确认**——若 `require_1m_aligned`，当前 1m K 线与方向一致。
5. **倾斜 / 价格区间**——阈值方向，可选 `min_skew_gap` 和 `max_entry_price`。
6. **期望值门槛**——`require_ev_gate` 开启时，启发式优势 ≥ `min_edge`。
7. **时段**——若启用时段过滤，UTC 小时未被阻止（或在白名单中）。
8. **多次轮询**——开仓前 `confirm_polls` 连续同向 GO。
9. **流动性 / 点差 / 报价时效**——通过配置的执行安全检查。
10. **仓位**——下注额、优势缩放、连亏缩放、最大名义金额、每日上限。
11. **离场策略**——止损、持有到结算、提前砍仓、`exit_before_sec`。
12. **模式**——先模拟盘 / 观察记录器；验证后才使用 `--execute`。

---

## 🧰 风险控制

默认值位于 `config/polybtc_profiles.yaml`，并在实盘路径强制执行：

- 每笔交易基础下注 + **按优势缩放** + **连亏软减仓**
- 每笔交易硬性**最大名义金额**
- 每日最大亏损 % 与每日最大交易数
- 最大连续亏损（硬性熔断）
- 报价时效、点差与盘口顶部流动性护栏
- 在可执行的**CLOB 买一价**止损
- 平仓限价下限（默认禁止 0.01 贱卖）
- 受控离场：持有到结算 / 提前砍仓 / 按时离场
- 可选极端倾斜微型对冲
- 时段允许 / 阻止（UTC）
- 优雅停止：SIGTERM → 等待 → SIGKILL

---

## ⚠️ 风险声明

本仓库是**教育 / 运维基础设施，不构成投资建议**。
请使用你自己的风险限额、每日亏损上限和资金控制。

**`observe` 仅供研究记录——切勿在其上启用实盘资金。**

---

## 💖 支持与贡献

如果这个技能对你的交易或研究有帮助，可以支持它的开发：

<p align="center">
  <a href="https://saweria.co/0xgetz">
    <img src="https://img.shields.io/badge/❤️%20捐赠-Saweria-ff5e00?style=for-the-badge" alt="通过 Saweria 捐赠"/>
  </a>
</p>

捐赠用于：

- 🖥️ 策略测试的服务器与数据源成本
- ✨ 新功能（动量过滤、多市场、仪表盘）
- 📚 更好的文档与示例
- 🐛 错误修复与日常维护

🔗 **https://saweria.co/0xgetz**

### 贡献

- Fork 本仓库
- 创建功能分支
- 提交你的更改
- 向 `main` 发起 Pull Request

欢迎提交 PR。
