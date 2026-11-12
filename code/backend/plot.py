"""植物口译员 · 生成最近7天土壤湿度曲线（给学长看的硬证据）"""
import os
import sqlite3
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]  # Windows 中文字体
plt.rcParams["axes.unicode_minus"] = False

DB_PATH = os.path.join(os.path.dirname(__file__), "plant.db")
OUT = os.path.join(os.path.dirname(__file__), "soil_7days.png")

con = sqlite3.connect(DB_PATH)
rows = con.execute(
    "SELECT ts, soil FROM readings ORDER BY ts"
).fetchall()
con.close()

times = [datetime.fromisoformat(r[0]) for r in rows]
soils = [r[1] for r in rows]
cutoff = datetime.now() - timedelta(days=7)
times, soils = zip(*[(t, s) for t, s in zip(times, soils) if t >= cutoff])

fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(times, soils, color="#2E7D32", linewidth=2)
ax.fill_between(times, soils, color="#2E7D32", alpha=0.12)
ax.axhline(30, color="#D32F2F", linestyle="--", linewidth=1)   # 缺水警戒线
ax.text(times[0], 31, "缺水警戒线 30%", color="#D32F2F", fontsize=10)
ax.set_ylim(0, 100)
ax.set_ylabel("土壤湿度 (%)")
ax.set_title("小绿的土壤湿度 · 最近7天", fontsize=14)
ax.grid(axis="y", alpha=0.3)
fig.autofmt_xdate()
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print("已生成:", OUT)
