# 四个报告入口：公开竞品结构与本站模板

调研日期：2026-11-11。以下“竞品公开展示”只描述其官方页面可核对的功能与报告结构；“本站设计”是 Drone Flight Report 的实现选择，不代表对方公司的内部交付标准。

| 入口 | 竞品公开展示 | 本站表单与 PDF 重点 | 当前边界 |
|---|---|---|---|
| 飞行性能 `/start/performance` | AirData 标准报告按日期、参与者、飞机和标签筛选飞行，保存模板并定期交付；Flight Reader 提供地图、事件时间线、图表和自定义报告。 | 输入单份日志，可加项目、飞机、客户编号。PDF 首页突出航程、时长、速度、高度基准；第二页提示数据质量。 | 一份飞行的自动草稿；不等于测绘精度或法规合规证明。 |
| 异常证据 `/start/incident` | RotorLab 的 Log Analyzer 先给日志概览、数据质量、地图与 3D 回放、图表和事件时间线；更深入的 Crash Analyzer 才加入诊断与置信度。 | 输入日志、用户描述的症状和大致事件时间，可附基线日志。PDF 首页与第二页将其写成“证据草稿”，标出事件顺序、用户描述和缺口。 | 不自动判定根因；用户症状不当作日志事实；人工审核须另行约定。 |
| 风数据参考 `/start/wind` | ArduPilot 文档说明 `XKF2.VWN/VWE` 可记录 EKF 风估计。Dronedesk 明确提醒环境风速未必在 DJI 日志里。公开资料未显示一套通用的“日志生成局地三维实测风场”标准模板。 | 输入日志和想分析的风问题。PDF 首页、证据页强调区域模型来源、可用高度剖面、机载估计与缺失项的区别；保留共用航线和时间轴。 | 不宣称局地 CFD、纯视觉反推风或三维实测风场已实现。 |
| 团队试点 `/start/team` | AirData 将飞行、任务、飞手、设备、维护和事件记录组织成可复用、可定期交付的报告；Flight Reader 的付费计划包括保留历史和自定义模板。 | 输入一份样本日志和组织、项目、飞机、飞手、客户编号。PDF 用“团队交付草稿”展示标签和审核边界，供讨论重复交付流程。 | 当前不提供团队账号、批量历史、审批或自动收费。 |

四个入口共用同一套日志解析、轨迹、时间轴、图表、风来源标注和技术附录。这样一份日志不会因为选了不同入口而得到互相矛盾的原始数据；变化的是上传时收集的业务上下文、PDF 前两页要回答的问题和交付状态。PDF 后续轨迹、遥测、风分析、垂直剖面、数据质量与方法页继续保留。

## 可核对的来源

- [AirData：Creating a Standard Flight Report](https://app.airdata.com/wiki/Help/Creating%2Ba%2BStandard%2BFlight%2BReport)
- [AirData：Reporting and Compliance](https://airdata.com/capabilities-reporting-and-compliance)
- [RotorLab：Log Analyzer](https://docs.rotorlab.app/forensics/log-analyzer/)
- [RotorLab：Crash Analyzer API fields](https://docs.rotorlab.app/api/reference/)
- [Flight Reader：Web plans and report features](https://www.flightreader.com/plans/)
- [Dronedesk：How the DJI flight log viewer works](https://logviewer.dronedesk.io/how-it-works)
- [ArduPilot：Windspeed estimation and barometer compensation](https://logbrowser.ardupilot.org/copter/docs/airspeed-estimation.html)
- [PIX4Dmatic：Quality report](https://support.pix4d.com/hc/en-us/articles/360040686852)（测绘质量报告的范围不同，不能用飞行日志 PDF 替代）
