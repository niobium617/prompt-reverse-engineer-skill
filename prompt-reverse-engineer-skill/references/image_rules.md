# 图像 Prompt 规则库

> 图像语义分析时的术语参考。Agent 提取的语义字段应尽量使用本库词汇，保证输出 Prompt 专业、可被生成模型准确理解。

## 一、图像 Prompt 要素顺序规范（七段结构）

标准结构（Midjourney / Stable Diffusion 通用，`model_mappings.md` 有逐模型细节）。**越核心的要素越靠前**——模型对前置内容的注意力权重更高：

| 段位 | 内容 | 覆盖语义字段 |
|---|---|---|
| ① 核心主体 | 画面核心对象的身份、外形、核心特征 | `subject`（前半） |
| ② 动作与状态 | 主体的姿态、行为、表情、互动关系 | `subject`（后半） |
| ③ 场景与环境 | 所处空间、背景元素、环境氛围细节 | `scene` |
| ④ 艺术风格 | 画风流派、创作媒介、参考风格 | `style` |
| ⑤ 光影色调 | 光照类型、光线方向、整体色彩基调 | `lighting` + `color` |
| ⑥ 镜头构图 | 拍摄视角、景别、构图方式 | `composition` |
| ⑦ 画质与质感 | 分辨率、精细度、特殊画面效果 | `photo_params` + `quality_words` |

机器渲染顺序（与模板 `assets/templates/*.json` 占位符一致）：

```
subject → scene → style → lighting → color → composition → photo_params → quality_words
```

语义字段填充时，`subject` 内先写**身份外形**（①），后写**动作状态**（②）；`lighting` 与 `color` 相邻渲染组成⑤；`photo_params` 与 `quality_words` 收尾组成⑦。

写法示例（字段示例与 `prompt_framework.md` 2.3 节一致）：

- **① 核心主体 + ② 动作与状态**（subject）：`年轻女性，黑色风衣，手持透明伞，回眸望向镜头，神情宁静`
- **③ 场景与环境**（scene）：`雨夜霓虹街头，潮湿反光地面，未来都市`
- **④ 艺术风格**（style）：`赛博朋克 / 胶片摄影 / 扁平插画`
- **⑤ 光影色调**（lighting + color）：`霓虹灯牌侧光，轮廓光勾勒，高对比夜色` + `深蓝紫为主，霓虹橙青点缀，高饱和冷色调`
- **⑥ 镜头构图**（composition）：`低角度仰拍，中景，三分法构图，人物居中偏右`
- **⑦ 画质与质感**（photo_params + quality_words）：`50mm 定焦，f/1.8 浅景深` + `超清细节, 8K, 电影级光影`

负向词（negative_words）单独成段（SD 的 Negative 段 / MJ 的 `--no` 参数），组织方式见第八节。

## 二、摄影参数表

| 类别 | 常见值 | 描述词示例 |
|---|---|---|
| 镜头类型 | 广角 / 标准 / 长焦 / 微距 / 移轴 / 鱼眼 | `wide-angle lens` `85mm telephoto` `tilt-shift` |
| 焦距 | 16 / 24 / 35 / 50 / 85 / 135 / 200 mm | 16mm 建筑风光、35mm 人文、50mm 标准人眼、85mm 人像、135mm 压缩特写 |
| 光圈 | f/1.4 ~ f/22 | f/1.4-f/2.8 浅景深虚化、f/8-f/11 全景清晰 |
| 快门 | 1/8000s ~ 30s | 高速凝固动作、慢门车流光轨/丝绢流水 |
| ISO | 50 ~ 25600 | 低 ISO 细腻、高 ISO 颗粒感 |
| 景深 | 浅 / 深 | `shallow depth of field, bokeh` / `deep focus` |

## 三、构图法则

| 构图 | 描述词（中/英） |
|---|---|
| 三分法 | 主体位于三分线交点 `rule of thirds` |
| 对称构图 | 左右/上下镜像平衡 `symmetrical composition` |
| 引导线 | 道路/栏杆将视线引向主体 `leading lines` |
| 框架式 | 门窗/拱廊框住主体 `framing` |
| 对角线 | 画面沿对角线展开 `diagonal composition` |
| 留白 | 大面积空白突出主体 `negative space` |
| 中心构图 | 主体居中 `centered composition` |
| 视角 | 平拍 `eye level` / 仰拍 `low angle` / 俯拍 `high angle` / 鸟瞰 `aerial view` / 过肩 `over-the-shoulder` |

## 四、光影术语

| 类别 | 术语与描述词 |
|---|---|
| 光源方向 | 顺光 / 侧光 `side lighting` / 逆光 `backlight` / 顶光 / 底光 |
| 光质 | 硬光 `hard light`（强烈阴影）/ 柔光 `soft light`（漫反射，阴天质感） |
| 经典布光 | 伦勃朗光 `Rembrandt lighting` / 轮廓光 `rim light` / 蝴蝶光 / 三点布光 |
| 特殊效果 | 剪影 `silhouette` / 霓虹光 `neon glow` / 体积光 `volumetric light`（丁达尔）/ 光斑 `lens flare` |
| 时段氛围 | 黄金时刻 `golden hour` / 蓝调时刻 `blue hour` / 夜色 / 黄昏 |
| 影调 | 高调 `high key`（明亮）/ 低调 `low key`（暗调）/ 电影感 `cinematic lighting` |

## 五、色彩

- **色相描述**：暖色系（红橙黄）/ 冷色系（蓝青紫）/ 中性色（黑白灰棕米）。
- **配色关系**：互补色（橙↔蓝，赛博朋克常用）/ 邻近色 / 类似色 / 单色 / 分离补色。
- **饱和度档位**：高饱和（鲜艳冲击）/ 中等（自然）/ 低饱和 `muted colors`（高级感）/ 黑白 `monochrome`。
- **常用风格色板**：
  - 赛博朋克：深蓝紫底 + 霓虹橙/品红/青点缀，高对比
  - 莫兰迪：低饱和灰调（豆沙/灰绿/雾蓝）
  - 胶片：颗粒感 + 偏色（青橙/褪色黄）
  - 马卡龙：高明度低饱和粉彩
  - 日系：高明度、低对比、清透

## 六、美术风格词库

| 类别 | 风格词 |
|---|---|
| 传统绘画 | 油画 `oil painting` / 水彩 `watercolor` / 水墨 `ink wash` / 版画 / 工笔 / 涂鸦 |
| 现代艺术 | 印象派 `impressionism` / 立体主义 / 超现实主义 `surrealism` / 波普 `pop art` / 极简主义 / 蒸汽波 `vaporwave` |
| 插画 | 扁平插画 `flat illustration` / 厚涂 / 线稿 `line art` / 绘本风 / 2.5D 等距 |
| 动漫 | 吉卜力风 `Ghibli style` / 新海诚风 `Makoto Shinkai style` / 日漫 / 美漫 / 像素风 `pixel art` |
| 数字艺术 | 赛博朋克 `cyberpunk` / 废土 `post-apocalyptic` / 科幻概念设计 `sci-fi concept art` / 低多边形 / 3D 渲染 `octane render` / 虚幻引擎 `unreal engine` |
| 摄影 | 纪实 / 街头 `street photography` / 时尚大片 / 人像 / 风光 / 微距 / 航拍 / 胶片 `film photography` / 宝丽来 |

## 七、常用质量词（quality_words）

`ultra detailed` `8K` `masterpiece` `best quality` `sharp focus` `high resolution` `cinematic lighting` `professional photography`

## 八、Negative 三类标准结构（negative_words）

负向词按「画面瑕疵 → 风格违和 → 内容违和」三类组织，同类集中放置、英文逗号分隔：

| 类别 | 用途 | 常见词（中/英） |
|---|---|---|
| 画面瑕疵 | 修正生成缺陷 | 模糊 `blurry`、低质量 `low quality`、`worst quality`、畸形 `deformed`、结构错误 `distorted anatomy`、多余肢体 `extra limbs`、比例失调 `bad proportions`、畸形手 `mutated hands`、水印 `watermark`、文字乱码 `text`、`signature`、过饱和 `oversaturated`、`artifacts` |
| 风格违和 | 排除不符合题材的风格 | 卡通 `cartoon`、Q 版 `chibi`、二次元 `anime`、明亮清新、现代整洁建筑等与目标题材冲突的风格 |
| 内容违和 | 排除不符合设定的元素 | 与场景设定冲突的人物（如空旷场景出现路人）、道具、鲜艳色彩等 |

Agent 填充 `negative_words` 字段时按三类分组书写（如 `"模糊, 低质量, 畸形, 多余肢体, 卡通, 明亮清新, 违和道具, 鲜艳色彩"`：瑕疵词在前、违和风格居中、违和内容收尾），渲染时统一逗号连接。

## 九、格式使用规范

1. **排序规则**：越核心的元素越靠前（第一节七段顺序），模型对前置内容的注意力权重更高。
2. **分隔方式**：不同元素用英文逗号分隔；同维度的描述集中放置，便于整体调整。
3. **权重强化**（Stable Diffusion 等支持权重语法的模型）：`(关键词:权重数值)` 格式，数值 >1 增强、<1 减弱，如 `(透明伞:1.3)`。**Midjourney 不支持此语法**——需突出某要素时用要素前置、`--stylize 0-1000` 或 `--chaos` 参数，勿在 MJ 输出中写 `(词:权重)` 标记。
4. **模块化复用**：替换对应段位的内容即可快速切换题材、风格，无需重写整段提示词。
