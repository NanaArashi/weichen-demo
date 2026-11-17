# -*- coding: utf-8 -*-
"""
微尘 · 数据分析脚本（pandas + matplotlib，从 SQLite 直接读）

用法：
    python analyze.py                       # 读 server/wc.db
    python analyze.py --db server/wc.db --out reports

输出：
    1) 控制台：数据质量报告 + A/B 组对比表 + 前后测变化 + 4 周留存
    2) reports/group_compare.png   两组平均反应时 / 改答率对比柱状图
    3) reports/retention.png       两组 4 周留存曲线

指标口径（写进 BP 就用这套话）
    反应时 RT   = trials.rt_ms，只保留 quality=ok 且 300ms < RT < 30000ms 的题
    改答率      = item_answer 里 rev>1（第二次及以后作答）的比例 → 强迫性检查行为的代理指标
    留存（周 w） = 该被试在第 w 周是否至少完成过 1 次练习（session_complete）
"""
import argparse
import os
import sqlite3
import sys

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

FAST_MS, SLOW_MS = 300, 30000


def load(db_path):
    conn = sqlite3.connect(db_path)
    try:
        part = pd.read_sql("SELECT * FROM participants", conn)
        trials = pd.read_sql("SELECT * FROM trials", conn)
        events = pd.read_sql("SELECT * FROM events", conn)
        assess = pd.read_sql("SELECT * FROM assessments", conn)
    finally:
        conn.close()
    return part, trials, events, assess


def quality_report(trials):
    n_all = len(trials)
    if n_all == 0:
        return {"采集": 0, "剔除": 0, "保留": 0}
    bad = trials[(trials["quality"].fillna("ok") != "ok") |
                 (trials["rt_ms"] < FAST_MS) | (trials["rt_ms"] > SLOW_MS)]
    kept = trials.drop(bad.index)
    print("【数据质量】采集 %d 题 → 剔除 %d 题（瞎点/走神/切屏重叠）→ 保留 %d 题"
          % (n_all, len(bad), len(kept)))
    if len(trials):
        print("           被剔除原因：", bad["quality"].value_counts().to_dict())
    return kept


def group_table(part, trials_ok, events, assess):
    arms = sorted(set(part["arm"].dropna().astype(str)) | {"A", "B"})
    rows = []
    for arm in arms:
        pids = part[part["arm"].astype(str) == arm]["pid"]
        t = trials_ok[trials_ok["pid"].isin(pids)]
        rt = t["rt_ms"].mean() if len(t) else float("nan")
        # rev: 1=第一次，0=回头改答
        mod = (1 - t["rev"].mean()) * 100 if len(t) else float("nan")
        n_sub = len(pids)
        sess = events[(events["type"] == "session_complete") & (events["pid"].isin(pids))]
        n_sess = len(sess)
        rows.append({
            "组别": arm, "被试数": n_sub, "有效题次": len(t),
            "平均反应时(ms)": None if pd.isna(rt) else round(rt),
            "改答率(%)": None if pd.isna(mod) else round(mod, 1),
            "完成练习次数": n_sess,
            "人均练习次数": round(n_sess / n_sub, 2) if n_sub else None,
        })
    df = pd.DataFrame(rows)
    print("\n【组间对比】")
    print(df.to_string(index=False))
    return df


def pre_post(assess, part):
    if assess.empty:
        return None
    df = assess.pivot_table(index="pid", columns="phase", values=["y", "s"], aggfunc="last")
    df.columns = ["%s_%s" % (a, b) for a, b in df.columns]
    df = df.reset_index()
    df["arm"] = df["pid"].map(part.set_index("pid")["arm"].to_dict())
    out = []
    for arm, g in df.groupby("arm"):
        row = {"组别": arm, "N(有前测)": int(g["y_pre"].notna().sum())}
        for m, name in (("y", "清洁困扰"), ("s", "情绪状态")):
            pre, post = g[m + "_pre"].mean(), g[m + "_post"].mean()
            row[name + " 前测"] = None if pd.isna(pre) else round(pre, 1)
            row[name + " 后测"] = None if pd.isna(post) else round(post, 1)
            row[name + " 变化"] = None if pd.isna(pre) or pd.isna(post) else round(post - pre, 1)
        out.append(row)
    print("\n【前后测变化】")
    print(pd.DataFrame(out).to_string(index=False))
    return df


def retention_curve(events, part, weeks=4):
    """每人从第一次练习起算周序，统计第 w 周仍有练习的比例"""
    sess = events[events["type"] == "session_complete"].copy()
    if sess.empty:
        print("\n【4 周留存】暂无练习记录")
        return None
    sess["ts"] = pd.to_numeric(sess["ts"], errors="coerce")
    first = sess.groupby("pid")["ts"].min().rename("first_ts")
    sess = sess.join(first, on="pid")
    sess["week"] = ((sess["ts"] - sess["first_ts"]) // (7 * 24 * 3600 * 1000)).astype(int) + 1
    sess = sess[(sess["week"] >= 1) & (sess["week"] <= weeks)]

    # 分母：每个组里"开始过练习"的人（有 first_ts 的）
    started = part[part["pid"].isin(first.index)].copy()
    started["arm"] = started["arm"].astype(str)
    curves = {}
    for arm in ["A", "B"]:
        base = started[started["arm"] == arm]
        base_n = len(base)
        vals = []
        for w in range(1, weeks + 1):
            active = sess[(sess["arm"] == arm) & (sess["week"] == w)]["pid"].nunique()
            vals.append(round(100 * active / base_n, 1) if base_n else float("nan"))
        curves[arm] = vals
        print("    %s 组（基数 %d 人）：第1-4周留存 %s%%" % (arm, base_n, vals))
    return curves


def plot_group(df, out_dir):
    if df is None or len(df) == 0:
        return
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    colors = {"A": "#4f9d8f", "B": "#d0a35a", "C": "#8a8fa3"}
    for ax, col, title in ((axes[0], "平均反应时(ms)", "平均作答反应时（越低越果断）"),
                           (axes[1], "改答率(%)", "改答率（越高＝越多回头检查）")):
        d = df[df[col].notna()]          # 该组还没有数据时不画 0，避免误导
        bars = ax.bar(d["组别"], d[col], color=[colors.get(a, "#999") for a in d["组别"]])
        ax.set_title(title, fontsize=11)
        ax.set_ylabel(col)
        for b, v in zip(bars, d[col]):
            ax.text(b.get_x() + b.get_width() / 2, v, str(v), ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    p = os.path.join(out_dir, "group_compare.png")
    fig.savefig(p, dpi=150)
    plt.close(fig)
    print("\n已保存：%s" % p)


def plot_retention(curves, out_dir, weeks=4):
    if not curves:
        return
    fig, ax = plt.subplots(figsize=(6, 4))
    xs = list(range(1, weeks + 1))
    colors = {"A": "#4f9d8f", "B": "#d0a35a"}
    for arm, vals in curves.items():
        ax.plot(xs, vals, marker="o", label="%s 组" % arm, color=colors.get(arm, "#999"))
    ax.set_xlabel("周次")
    ax.set_ylabel("仍在使用比例 (%)")
    ax.set_title("4 周留存曲线")
    ax.set_ylim(0, 105)
    ax.set_xticks(xs)
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    p = os.path.join(out_dir, "retention.png")
    fig.savefig(p, dpi=150)
    plt.close(fig)
    print("已保存：%s" % p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "server", "wc.db"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports"))
    a = ap.parse_args()
    if not os.path.exists(a.db):
        print("找不到数据库：%s\n先把 server/app.py 跑起来，让被试产生数据。" % a.db)
        sys.exit(1)
    os.makedirs(a.out, exist_ok=True)

    part, trials, events, assess = load(a.db)
    print("【样本】被试 %d 人，题次 %d，事件 %d，评估 %d\n"
          % (len(part), len(trials), len(events), len(assess)))
    trials_ok = quality_report(trials)
    df = group_table(part, trials_ok, events, assess)
    pre_post(assess, part)
    print("\n【4 周留存】")
    curves = retention_curve(events, part)
    plot_group(df, a.out)
    plot_retention(curves, a.out)


if __name__ == "__main__":
    main()
