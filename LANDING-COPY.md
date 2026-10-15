# Landing Page Copy + SEO — Drone Flight Report

面向：全球 / 海外（英文为主）。目标：把免费出报告做成获客入口。

---

## 1. 首屏（Hero）

**H1:** Turn any drone flight log into a clear flight report — in seconds.

**Sub:** Upload a DJI, ArduPilot, or PX4 log. Get flight statistics, a flight-health
check, a regional wind reference, and a downloadable PDF report. Free, no signup.

**主 CTA:** `Generate my report` ｜ **次 CTA:** `See a demo`

**信任条（小字）：** Works with DJI · ArduPilot DataFlash (`.BIN`) · PX4 ULog (`.ulg`) · CSV / TXT

---

## 2. 三个卖点（Feature cards）

1. **Any log, one standard format** — We normalize DJI / ArduPilot / PX4 logs into one
   schema, so you get the same clean report no matter what you flew.
2. **Flight health at a glance** — A 0–100 score with plain-English flags: GPS quality,
   timeline gaps, altitude spikes, speed sanity. Know if a flight was clean.
3. **Privacy-first by design** — Your original log is deleted right after processing.
   Sharing de-identified data is off by default and requires an explicit opt-in.

（面向海外的差异化卖点：跨厂商 + 隐私优先 / GDPR-friendly）

---

## 3. 三步说明（How it works）

1. **Upload** your flight log (CSV, `.bin`, `.ulg`).
2. **We analyze** trajectory, statistics, health and regional wind.
3. **Download** your report as a PDF — or share a link.

---

## 4. 隐私承诺块（信任）

> **Your data stays yours.** The original log is processed in a temporary file and
> deleted immediately. Generated files are removed after 24 hours. We never keep your
> filename, name, or IP with your flight data. See our [Privacy policy](/privacy).

---

## 5. FAQ（同时喂 SEO / FAQ schema）

- **Which formats are supported?** DJI CSV exports, ArduPilot DataFlash `.bin`,
  PX4 ULog `.ulg`, and generic CSV/TXT.
- **Is it free?** Yes — generating a report is free, no signup required.
- **Do I keep the copyright of my data?** Yes. We only process it to produce your report.
- **How accurate is the wind data?** It is a *regional historical* weather reference
  (Open-Meteo / NASA POWER), not a local real-time measurement.
- **Can I analyze PX4 ULog files online?** Yes — upload the `.ulg` and get a report.

---

## 6. SEO 配置

**Title tag (≤60 字符):**
`Drone Flight Log Analysis & Report Generator — Free Online`

**Meta description (≤155 字符):**
`Upload DJI, ArduPilot or PX4 drone logs and get flight statistics, a health check,
regional wind and a PDF report. Free, private, no signup.`

**目标关键词（按意图排序）：**

| 关键词 | 意图 | 落地页 |
|---|---|---|
| dji flight log analysis | 交易 | 首页 |
| drone flight report generator | 交易 | 首页 |
| px4 ulog viewer online | 交易 | 首页 / /demo |
| ardupilot .bin log analysis | 交易 | 首页 |
| drone telemetry analysis tool | 混合 | 首页 |
| how to read dji flight logs | 信息 | 博客 |
| what is a ulog file | 信息 | 博客 |
| gps hdop meaning drone | 信息 | 博客 |
| drone flight data privacy / gdpr | 信息 | /privacy |
| flight log to pdf | 交易 | 首页 |

**结构化数据（FAQ schema，放 `<head>`）：**

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {"@type":"Question","name":"Which drone log formats are supported?",
     "acceptedAnswer":{"@type":"Answer","text":"DJI CSV, ArduPilot DataFlash .bin, PX4 ULog .ulg, and CSV/TXT."}},
    {"@type":"Question","name":"Is the drone flight report generator free?",
     "acceptedAnswer":{"@type":"Answer","text":"Yes. Generating a report is free and requires no signup."}},
    {"@type":"Question","name":"Is my flight data private?",
     "acceptedAnswer":{"@type":"Answer","text":"Your original log is deleted right after processing. Sharing de-identified data is off by default and opt-in."}}
  ]
}
</script>
```

**hreflang：** 英文主站 `en`；需要时再加 `zh`（中文版），别只做中文，你面向海外。

---

## 7. 转化钩子（后续 A/B）

- 报告页底部：「Email me this report / 收藏」→ 邮箱收集 → 后续转付费机队功能。
- 健康分低的报告 → 「Want alerts for your whole fleet? Join the beta.」
