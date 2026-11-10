"""_fill_item / _fill_tip 演示：补位条目按天轮换措辞、写入当天城市，多天不会出现同一句（纯函数，无需密钥）"""
from app.tools.state_transition import _fill_item, _fill_tip

for day, city in [(1, "天津"), (2, "天津"), (3, "上海")]:
    print(f"第 {day} 天（{city}）上午 → {_fill_item('morning', day, city)[:34]}…")
print("没有城市信息     →", _fill_item("noon", 1, "")[:30], "…")
print("小贴士第 1 / 2 天 →", _fill_tip(1, "上海")[:24], "… |", _fill_tip(2, "上海")[:24], "…")