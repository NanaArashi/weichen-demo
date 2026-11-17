# CHANGES · 微尘 Demo 修复与埋点改造

改造日期：2026-11-16
工作副本：`E:\微尘_实验版\`（原件完整保留在 `_orig\` 里，可随时对照/回滚）
未触碰：`<img src>`、`background-image:url()`、favicon、SVG 引用、字体文件名 —— **一个字没改**（唯一例外见文末"字体 404"）

---

## 一、四个页面都做了的事（公共改动）

| # | 改了什么 | 为什么 |
|---|---|---|
| 1 | `wc_track.js` 挂到 `<head>` | 埋点引擎，全站共用 |
| 2 | Google Fonts 图标链接 → `libs/material-symbols.css`（本地 3.9 MB 字体） | 断网/校园网不稳时图标不会变成一串英文单词 |
| 3 | `cdn.tailwindcss.com` → `libs/tailwind.js` | 同上，assessment 页样式完全依赖它 |
| 4 | `echarts@5.4.3` → `libs/echarts.min.js` | 首页曲线图 |
| 5 | `chart.js@4.4.1` → `libs/chart.umd.min.js` | 训练页曲线图 |

> 现在**完全离线可跑**，`libs\` 目录别删。

---

## 二、register.html（4 处）

| 位置 | 改前 | 改后 |
|---|---|---|
| 表单下方提示（原 L537） | `演示提示：…输入演示账号 <b>ylq20070820</b>，密码 <b>88888888</b>` | `账号请填写你的被试编号（如 <b>WC001</b>），密码自设（至少 6 位）` |
| 提交校验 `registerForm submit` | `if (account === 'ylq20070820' && pass === '88888888')` | `if (account.length > 0 && pass.length >= 6)` —— 不再有写死账号 |
| 校验失败 alert | 还提示了一遍演示账号密码 | `请填写被试编号（如 WC001），密码至少 6 位` |
| 医师端卡片文案 | "支持为患者建立个性化训练计划…"（暗示功能已实现） | 改为"该模块尚未开放，现阶段仅接受申请开通" |

新增功能：
- 提交成功时 `WC.setPid(账号)` 把被试编号写进埋点身份；
- 记录 `register_submit` 事件，**年龄只记分段**（`18-22` 这种），函数 `ageBandOf()`，不存原始年龄数值；
- 浮窗 AI 从"回声"改为只回字数："已记录（N 字）。这里只做情绪记录，不是对话分析。" **不再把用户原文弹回来**。

---

## 三、assessment.html（10 处）

| 位置 | 改前 | 改后 |
|---|---|---|
| `scales.ybocs.name` | `Y‑BOCS 强迫量表` | `清洁困扰自评（自编初筛）` |
| `scales.ybocs.note` | "耶鲁‑布朗强迫量表…" | "本项目自编的初筛条目，非临床诊断工具" |
| `scales.sds.name` | `SDS 情绪自评量表` | `情绪状态自评（自编初筛）` |
| `scales.sds.note` | "抑郁自评量表…" | "本项目自编的情绪条目，非临床诊断工具" |
| 两个 tab 按钮文案 | Y‑BOCS / SDS | 清洁困扰自评 / 情绪状态自评 |
| `progressLabel` 初始文案 | Y‑BOCS … | 清洁困扰自评 … |
| 第一段结束弹窗标题 | `Y-BOCS 评估完成` | `初筛完成` |
| 弹窗按钮 | `继续填写 SDS` | `继续填写情绪状态` |
| `showFinalResult()` | 算完分数就丢，什么都不存 | 写入 `localStorage.weichen_assess_v1`（y/s/levelY/levelS/ts），并 `WC.track('assess_final')` |
| `resultWrap` 末尾 | 无免责声明 | 动态插入一段灰字：初筛参考、非诊断、只记行为不记身份 |

**没改**：`scales` 的键名仍是 `ybocs`/`sds`（改了会连带崩 CSS `#tabYbocs` 和一堆引用，不值当）；题目内容、分值与阈值原样保留。

埋点新增三处：

| 函数 | 埋点 |
|---|---|
| `render()` | `WC.show('ybocs:3')` —— 每题出现时开始计时（用于算 RT） |
| `selectOption()` | `WC.answer(key, value)` —— 算用时、判质量、记第几次改答 |
| `prev()` | `WC.track('item_revisit')` —— 回头改答行为本身就记一笔 |
| `switchTab()` | `WC.track('tab_switch')` |

---

## 四、training.html（6 处）

| 位置 | 改前 | 改后 |
|---|---|---|
| `DEFAULT_STATE.level` | `3`（新用户一进来就"已走过 2 阶"） | `1` |
| `ensureConsent` 五、你的数据 | "只保存在本机，不会上传到任何服务器"（上线后成不实陈述） | 改成"默认本机；走在线地址时行为数据会上传到研究服务器，文字内容不保存，可随时要求删除" |
| `ensureConsent` 新增第六段 | —— | 明确告知"两种界面版本、随机分配、只在打卡/连续天数/成就上不同" |
| `startPractice()` | 无 | `WC.track('practice_start', {lv, mins})` |
| `recordAnxiety()` | 无 | `WC.track('anxiety_record', {v, first, last, high})` |
| `completeSession()` | 无 | `WC.track('session_complete', {lv, mins, before, after, bg, streak})` —— **前后测焦虑值天然在此落地** |
| `resetDemoData()` | 只删训练状态 | 同时删评估结果 + `WC.clearAll(true)` |
| 启动段（`renderHome()` 之后） | 无 | `WC.init({page:'training'})` + **评估结果打通**：读 `weichen_assess_v1`，首次进入弹一段"上次初筛结果已带过来" |

> 打通效果：评估页算完的分数，训练页第一次打开会主动告诉你（"0 分 / 几乎无"这种），再也不是两个互不相干的页面。

---

## 五、home.html（3 处）

| 位置 | 改前 | 改后 |
|---|---|---|
| 某入口按钮 | `location.href='charts.html'` → 文件不存在，点了 404 | 改成提示"成长曲线功能还在开发中，可以先在训练页「我的变化」里看" |
| `sendAiMood()` | `console.log` + `alert('收到你的想法：'+text)`（假 AI） | `WC.track('ai_text_input', WC.textLen(...))` + 只回字数，不回声原文 |
| 页尾 | 无 | `WC.init({page:'home'})` |

`href="home.html"` 本来就对（这个文件夹里文件名就是 home.html），没动。

---

## 六、新增文件

| 文件 | 作用 |
|---|---|
| `wc_track.js` (v1.2) | 埋点引擎：`page_view / item_show / item_answer / item_revisit / tab_switch / practice_start / anxiety_record / session_complete / assess_final / assess_bridge / register_submit / ai_text_input / subject_bound`；含切屏计时、质量标记 `ok/too_fast/too_slow/hidden_overlap`、`health()` 自查、JSONL 导出、`endpoint` 一键上云 |
| `research.html` | 研究者控制台：采集状态、绑定被试编号与 A/B 组、导出、清空、流程提示。**正式发被试前删掉或加口令** |
| `server/collect.py` | 零依赖数据收集服务（POST /events → data/events.jsonl） |
| `部署上线指南.md` | 三档上线路径 + 合规检查清单 |
| `libs/` | echarts / chart.js / tailwind / Material Symbols 全套本地化 |

---

## 七、实测记录（不是"应该能跑"，是真点过）

本地 `python -m http.server 8765` 起服务，浏览器实操：

- 研究者页绑定 `WC001 / A` → 首页 → 评估页作答 6 题 → 事件里 `pid=WC001 arm=A` 正确带入
- 评估页：6 题走完弹"初筛完成"，再走 5 题出结果，`scoreY/scoreS` 计算正常，
  `weichen_assess_v1` 写入 `{"y":0,"s":0,"levelY":"几乎无 / 极轻","levelS":"稳定"}`
- 训练页：开页先弹"初筛结果已带过来"，滑动到底后同意按钮才亮（原有逻辑），
  进入 `Lv.1 · 触碰门把手`（不再是 Lv.3），完成一次练习后
  `levelCounts={"1":1}`、`history=[{"before":7,"after":7}]`
- 首页输入 12 个字 → 事件里只有 `{"ch":12,"wd":0,"total":12}`，**没有原文**
- 收集服务自测：`POST /events` → `{"ok":true,"n":1}`，`GET /health` → `{"total":1}`
- 全部内联脚本 `node --check`：**0 处语法错误**

---

## 八、顺手修的一个原有 bug

`fonts` 目录里文件名是 `honglei.otf.otf`，但 CSS 写的是 `url("fonts/honglei.otf")` → 一直 404。
已复制一份 `fonts\honglei.otf`（原文件名保留未动）。

---

## 九、第二轮改造：三项实验（A/B/C）+ 后端 + 分析脚本

### 界面差异（training.html）
| 元素 | A 柔性 | B 游戏化 | C 无进度 |
|---|---|---|---|
| 阶梯 / SUDS | ✅ | ✅ | ✅ |
| 累计分钟·次数·成长树 | ✅ | ✅ | ❌ |
| 焦虑曲线 | ✅ | ✅ | ❌ |
| 星光图鉴（被动可见） | ✅ | ✅ | ❌ |
| 打卡按钮 + 14 天日历 | ❌ | ✅ 新增 | ❌ |
| 连续打卡天数 | ❌ | ✅ 新增 | ❌ |
| 升级弹窗 | ❌ | ✅ | ❌ |
| 图鉴主动查看入口 | ❌ | ✅ 新增 | ❌ |

实现方式：`body[data-arm]` + 一段 CSS 控制显隐，一份页面三种界面，不存在三套代码不同步。
组别来源 `localStorage.wc.arm`；A/B 由注册页 50/50 随机；C 只在研究者页手动指定（先导用）。

### 埋点修正
| 问题 | 处理 |
|---|---|
| `item_answer` 里没有单题反应时 | 增加 `rtMs` 字段（之前只有页内相对时间，DDM 用不了） |
| 跳页面时用 sendBeacon 乐观标记"已上报"，实际会丢（实测 17 条只剩 7 条） | 改 fetch keepalive，**只有服务器回 2xx 才标记**，失败留本地、进页面自动补传 |
| 攒数据靠关页面 | 攒 6 条自动发一次 + 20 秒兜底 |
| 结果页重复触发 `assess_final`，会被后端误判成后测 | 前端每页只报一次 + 后端 30 分钟内同分去重 |
| B 组新交互无埋点 | 新增 `checkin_click` / `streak_view` / `atlas_open` / `upgrade_dismiss` / `arm_assigned` |

### 新增文件
| 文件 | 作用 |
|---|---|
| `server/app.py` | 零依赖后端（http.server + sqlite3），自动分表 participants / trials / events / assessments，接口 `/api/events`、`/api/health`、`/api/export` |
| `analyze.py` | pandas + matplotlib：质量报告、A/B 反应时与改答率对比图、前后测变化、4 周留存曲线 |
| `实验方案与实现说明.md` | 三组定义、代码落点、字段↔表映射、60 人排期、答辩口径 |

### 实测记录（第二轮）
- 注册页提交 → 自动随机，`arm=B`，`pid` 正确绑定
- B 组：打卡卡可见 → 打卡后「连续 1 天」、日历亮 1 格；图鉴入口弹出「我的星光图鉴（0 / 6）」
- A 组：打卡卡 `none`、图鉴入口 `none`、仪表盘仍在
- C 组：仪表盘 / 曲线卡 / 图鉴标题全部 `none`，阶梯仍在（2 张 stage 卡）
- 全链路：11 题 + 1 次练习 → 后端落 `trials 16`、`assessments pre`、事件含 `register_submit / arm_assigned / assess_bridge / practice_start / anxiety_record / session_complete`
- `analyze.py` 出图成功（中文正常，空组不画 0）
- 全部内联脚本 `node --check`：**0 处语法错误**

---

## 十、还没做（需要你点头才动）

1. **BP 里的失实表述**（5.1.1 顾问团队、5.2.1 伦理审核、7.2 外部顾问、第十二章空附件）：
   属于 BP 修订，不在代码范围。
2. **`home.html` 的 `主页bg.jpg` 没人引用**（只用了 `主页1bg.jpg`）：留着不占事，想清可以删。
3. **PyDDM 拟合**：等真实数据量够了再做，现在做就是编数据。
