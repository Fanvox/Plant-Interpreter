"""
植物口译员 · 后端
功能：接收 ESP32 上传的数据 -> 存 SQLite -> 状态变化时调 LLM 生成植物文案 -> Server酱推送微信

运行：python app.py   （在电脑上常驻运行）
"""

import json
import os
import sqlite3
import time
from datetime import datetime

import requests
from flask import Flask, jsonify, request

# ==================== 配置（改这三处就能跑） ====================
SENDKEY = "SCT你的Server酱SendKey"          # https://sct.ftqq.com/ 免费申请
LLM_API_KEY = "你的智谱APIKey"          # 推荐 GLM-4-Flash（免费）：https://open.bigmodel.cn
LLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
LLM_MODEL = "glm-4-flash"

DB_PATH = os.path.join(os.path.dirname(__file__), "plant.db")

PLANT_NAME = "小绿"       # 给植物起名
PLANT_TYPE = "绿萝"       # 植物品种
PUSH_MAX_PER_DAY = 5      # 每日推送上限，防止 LLM 刷屏刷爆额度
# ================================================================

app = Flask(__name__)

# ---------- 状态判定规则（确定性代码：语义归LLM，判定归规则） ----------
# 阈值按经验先设，跑一周后按真实数据微调
def judge(soil: int) -> str:
    if soil < 30:
        return "very_thirsty"
    if soil < 55:
        return "thirsty"
    if soil > 85:
        return "waterlogged"   # 刚浇完水 / 水浇多了
    return "fine"

STATE_LABEL = {
    "very_thirsty": "严重缺水",
    "thirsty": "有点渴",
    "fine": "状态不错",
    "waterlogged": "刚喝饱水",
}

PERSONA = (
    f"你是{PLANT_NAME}，一盆生活在大学生宿舍里的{PLANT_TYPE}，你会用第一人称发朋友圈。"
    "要求：不超过40个字；口语化、有性格；根据心情状态选语气——"
    "「有点渴」时撒娇提醒，「严重缺水」时委屈抱怨（别太凶），「状态不错」时开心或闲聊一句，"
    "「刚喝饱水」时感谢主人浇水。只输出朋友圈正文，不要任何解释和引号。"
)

_last_state = {"value": None, "date": None, "sent_today": 0, "last_push_ts": 0}


# ---------- 存储 ----------
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS readings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        soil INTEGER NOT NULL,
        air_temp REAL, air_hum REAL)""")
    con.commit()
    con.close()


def save_reading(soil, air_temp, air_hum):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO readings(ts, soil, air_temp, air_hum) VALUES (?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), soil, air_temp, air_hum),
    )
    con.commit()
    con.close()


# ---------- LLM 文案 ----------
def gen_message(state: str, soil: int, dry_days: float) -> str:
    mood = STATE_LABEL[state]
    extra = f"已经{dry_days:.0f}天没喝水了。" if dry_days >= 1 else ""
    user = (
        f"当前土壤湿度 {soil}%（{mood}）。{extra}"
        f"空气温度未知、主人是大一学生。写一条朋友圈。"
    )
    try:
        resp = requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": PERSONA},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.8,
                "max_tokens": 100,
            },
            timeout=20,
        )
        text = resp.json()["choices"][0]["message"]["content"].strip().strip('"“”')
        return text or f"（{PLANT_NAME}今天不想说话）"
    except Exception as e:
        print("LLM调用失败，降级为固定文案:", e)
        return f"【{PLANT_NAME}】土壤湿度{soil}%，{mood}。"


# ---------- 推送（Server酱） ----------
def push_wechat(title: str, body: str):
    requests.post(
        f"https://sctapi.ftqq.com/{SENDKEY}.send",
        data={"title": title, "desp": body},
        timeout=10,
    )


# ---------- 推送节流：状态变化才发 + 每日上限 + 冷却 ----------
def should_push(state: str) -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    now = time.time()
    if _last_state["date"] != today:  # 跨天重置计数
        _last_state["date"], _last_state["sent_today"] = today, 0
    if _last_state["value"] != state:          # 状态变了 -> 核心触发条件
        _last_state["value"] = state
        return _last_state["sent_today"] < PUSH_MAX_PER_DAY
    if state == "very_thirsty" and now - _last_state["last_push_ts"] > 6 * 3600:
        return _last_state["sent_today"] < PUSH_MAX_PER_DAY  # 严重缺水时6小时催一次
    return False


# ---------- 接口 ----------
@app.route("/data", methods=["POST"])
def receive():
    data = request.get_json(force=True, silent=True) or {}
    soil = data.get("soil")
    if soil is None:
        return jsonify({"error": "missing soil"}), 400
    soil = int(soil)
    save_reading(soil, data.get("air_temp"), data.get("air_hum"))

    state = judge(soil)
    print(f"[{datetime.now():%H:%M:%S}] soil={soil}% state={state}")

    if SENDKEY.startswith("你的"):
        return jsonify({"ok": True, "state": state, "push": "未配置SendKey，跳过推送"})

    if should_push(state):
        # 距上次浇水（湿度>85）经过的天数，喂给LLM做叙事
        con = sqlite3.connect(DB_PATH)
        row = con.execute(
            "SELECT ts FROM readings WHERE soil > 85 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        con.close()
        dry_days = 0.0
        if row:
            dry_days = (datetime.now() - datetime.fromisoformat(row[0])).total_seconds() / 86400

        msg = gen_message(state, soil, dry_days)
        title = f"{PLANT_NAME}｜{STATE_LABEL[state]}"
        push_wechat(title, f"{msg}\n\n> 土壤湿度 {soil}% · {datetime.now():%m-%d %H:%M}")
        _last_state["sent_today"] += 1
        _last_state["last_push_ts"] = time.time()
        return jsonify({"ok": True, "state": state, "pushed": msg})

    return jsonify({"ok": True, "state": state, "push": "无需推送"})


@app.route("/history", methods=["GET"])
def history():
    days = int(request.args.get("days", 7))
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT ts, soil FROM readings WHERE ts >= datetime('now', 'localtime', ?) ORDER BY ts",
        (f"-{days} days",),
    ).fetchall()
    con.close()
    return jsonify(rows)


if __name__ == "__main__":
    init_db()
    # 0.0.0.0：允许局域网内的 ESP32 访问本机
    app.run(host="0.0.0.0", port=5000)
