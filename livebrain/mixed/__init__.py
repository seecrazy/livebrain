"""混播引擎（V4.2 增补，DESIGN §7.7）：AI 与真人同场编排。

- schedule.py：混播排班器（时段表驱动 AI/真人切换）
- capture.py：真人采集通道（摄像头/麦克风，M1 提供 Mock）

画面切换与标识策略在 execution/pipeline.py（复用打断过渡段的交叉淡化机制）。
"""
