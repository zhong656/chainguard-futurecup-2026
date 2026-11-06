---
doc_id: "a3_basler_camera_selection"
title: "Camera Selection（工业相机选型指南）"
institution: "Basler AG"
doc_no: ""
url: "https://www.baslerweb.com/en-in/learning/camera-selection"
legal_basis: "同 A2，Basler AG《Legal notice》：引用须标明来源并附可点击 HTML 链接，未授予任何许可；分辨率计算式属《著作权法》第五条(三)的通用公式"
redistribution: "禁止复制网页正文；通用公式与事实可自由使用"
attribution: "写明「引自 Basler AG」并附可点击原页链接"
retrieved_at: 2026-11-07
content_type: original-paraphrase
third_party_text_included: false
supports: [技术选型, 相机选型对比表, 分辨率计算]
---

# Camera Selection（工业相机选型指南）

- 来源机构：Basler AG
- 编号 / 标识：无
- 官方链接：[Basler AG 原页](https://www.baslerweb.com/en-in/learning/camera-selection)
- 核验日期：2026-11-07
- 本文件性质：**本团队原创转述**，不含任何第三方作品原文、长段引用、图片或网页版式。

## 一、可核验事实（不受著作权保护）

- 分辨率 = 被测物尺寸 / 需要检出的最小缺陷尺寸
- 面阵相机：矩形传感器、多行像素同时曝光；线阵相机：1–3 行像素逐行曝光并拼接；3D 相机：ToF、立体视觉、结构光
- 线阵相机典型场景：传送带高速检测、印刷、分拣、包装、食品、表面检测
- CMOS 读出快且灵活；CCD 灵敏度与画质上限高但受限於高速场景
- 面阵相机帧率依接口不同可从 10 fps 到 340 fps；线阵场景称 line rate
- 原文算例：2000 mm / 1 mm = 2000 px（x、y 各 2000），约需 4 MP

## 二、本团队转述要点（原创表达）

1. 选型起点是先回答两句：要看到什么，以及相机必须具备什么特性才能看到，之后才比较型号。
2. 面阵适合静态或一般工业取像；线阵适合连续运动表面的高速检测；3D 用于需要深度信息的场景。对本示范场景（产线表面缺陷检测），线阵是最直接的对应项。
3. 分辨率下限可由「被测物幅宽 ÷ 最小缺陷尺寸」直接算出，再结合产线速度推出帧率下限——这两个数必须写进参数表，不能只写「选用高清工业相机」。
4. 高速运动场景必须匹配全局快门，否则会出现卷帘畸变。

## 三、权利依据与使用边界

- 依据：同 A2，Basler AG《Legal notice》：引用须标明来源并附可点击 HTML 链接，未授予任何许可；分辨率计算式属《著作权法》第五条(三)的通用公式
- 再分发判定：禁止复制网页正文；通用公式与事实可自由使用
- 署名要求：写明「引自 Basler AG」并附可点击原页链接

## 四、这份资料禁止做的事

- 大段复制英文原文或表格
- 用于广告或商业宣传
- 去掉来源标注与链接

## 五、引用写法（可直接抄进方案书）

> 引自 Basler AG《Camera Selection（工业相机选型指南）》，官方链接：https://www.baslerweb.com/en-in/learning/camera-selection。本项目仅引用其事实性结论，未复制原文内容。
