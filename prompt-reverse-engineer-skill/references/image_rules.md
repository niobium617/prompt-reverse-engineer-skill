# 图像 Prompt 规则库

> 图像语义分析时的术语参考。Agent 提取的语义字段应尽量使用本库词汇，保证输出 Prompt 专业、可被生成模型准确理解。
> 场景化入口（剧本/小说/文章 → 逐场景图片提示词）：字段契约见 `prompt_framework.md` 2.5 节，渲染由 `prompt_compiler.py scenes` 完成，本节七段规范同样适用。

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

> 2026 年后的模型（MJ V8.2、FLUX.2、GPT Image 2.5、Nano Banana Pro）对「质量词堆叠」的收益明显下降：保留 2-4 个有效词即可，把预算放在主体细节、镜头与光线描述上。GLM/老版 SD 才需要长串质量词。

## 八、Negative 三类标准结构（negative_words）

负向词按「画面瑕疵 → 风格违和 → 内容违和」三类组织，同类集中放置、英文逗号分隔：

| 类别 | 用途 | 常见词（中/英） |
|---|---|---|
| 画面瑕疵 | 修正生成缺陷 | 模糊 `blurry`、低质量 `low quality`、`worst quality`、畸形 `deformed`、结构错误 `distorted anatomy`、多余肢体 `extra limbs`、比例失调 `bad proportions`、畸形手 `mutated hands`、水印 `watermark`、文字乱码 `text`、`signature`、过饱和 `oversaturated`、`artifacts` |
| 风格违和 | 排除不符合题材的风格 | 卡通 `cartoon`、Q 版 `chibi`、二次元 `anime`、明亮清新、现代整洁建筑等与目标题材冲突的风格 |
| 内容违和 | 排除不符合设定的元素 | 与场景设定冲突的人物（如空旷场景出现路人）、道具、鲜艳色彩等 |

Agent 填充 `negative_words` 字段时按三类分组书写（如 `"模糊, 低质量, 畸形, 多余肢体, 卡通, 明亮清新, 违和道具, 鲜艳色彩"`：瑕疵词在前、违和风格居中、违和内容收尾），渲染时统一逗号连接。

**支持范围**：MJ（`--no`）与 SD（独立 Negative）生效；FLUX.2 不支持负向，需改写为正向约束（如「干净背景，无文字」）；GPT Image / Nano Banana 只宜把关键排除项写进 Constraints，不要整段照搬负向词。

## 九、格式使用规范

1. **排序规则**：越核心的元素越靠前（第一节七段顺序），模型对前置内容的注意力权重更高。
2. **分隔方式**：不同元素用英文逗号分隔；同维度的描述集中放置，便于整体调整。FLUX.2 / GPT Image / Nano Banana 改用完整句子或分段标签，见第十节。
3. **权重强化**（Stable Diffusion 等支持权重语法的模型）：`(关键词:权重数值)` 格式，数值 >1 增强、<1 减弱，如 `(透明伞:1.3)`。**Midjourney 不支持此语法**——需突出某要素时用要素前置、`--stylize 0-1000` 或 `--chaos` 参数，勿在 MJ 输出中写 `(词:权重)` 标记。FLUX.2 也不支持权重语法。
4. **模块化复用**：替换对应段位的内容即可快速切换题材、风格，无需重写整段提示词。
5. **参考图**：有参考图时在 `reference_note` 写明每张图的角色（人物造型 / 风格 / 构图 / 配色）；MJ V8 用 Edit Model，SD 用 IP-Adapter/ControlNet，FLUX.2 / GPT Image / Nano Banana 直接随请求附图。
6. **画内文字**：需要精确渲染的文字放 `text_content`，并在提示中要求逐字复现；不要在 `subject` 里混写长段文字。

## 十、现代图像模型的写法差异

| 模型 | 负向支持 | 推荐写法 | 参考图 | 文字渲染 |
|---|---|---|---|---|
| Midjourney V8.2 | `--no` | 逗号标签 + 参数；质量词从简 | Edit Model，最多 4 张 | 中等，短文本用「」包裹 |
| Stable Diffusion 3.5 | 独立 negative | 标签 + 权重语法；正负分离 | IP-Adapter / ControlNet | 弱 |
| FLUX.2 [pro] | **不支持** | 自然语言长句，描述关系与空间 | 多参考图，标注角色 | 较好 |
| GPT Image 2.5 | 写进 Constraints | 结构化规格书；编辑一次只改一项 | 随请求附图 | 强，逐字复现 |
| Muse Image 1.0 | 无独立 negative 参数，用 `Avoid:` 自然语言 | 自然语言完整句；先目标后主体/空间关系；参考图写明角色与禁止迁移 | 多图，角色 + 用途 + 迁移边界 | 强；海报任务仍需核对 |
| Nano Banana Pro | 改写为正向约束 | 主体+动作 → 地点 → 构图 → 风格 | API 最多 14 张 | 最强，海报级 |

选型建议：追求构图/风格一致 → MJ V8.2 或 FLUX.2；需要准确文字与编辑 → GPT Image 2.5 / Nano Banana Pro；复杂多主体空间关系、多图融合、系列一致性 → Muse Image 1.0（规则见 `muse_image_rules.md`）；本地可控与负面词 → SD 3.5。

## 十一、空间、材质与编辑约束术语

> 复刻、编辑、参考生成、多图融合（`prompt_framework.md` 2.3.1 的 recreate / edit / reference_guided / compose）时，除七段结构外还要写清空间、材质与改动边界。

### 11.1 空间关系（spatial / subject_position）

| 维度 | 术语 | 说明 |
|---|---|---|
| 九宫格位置 | 左上 / 上中 / 右上 / 左中 / 中心 / 右中 / 左下 / 下中 / 右下 | 先给格子，再补「略高/略低、偏左/偏右」 |
| 景深层次 | 前景 `foreground` / 中景 `midground` / 背景 `background` | 逐层写「有什么」，避免只写主体 |
| 遮挡关系 | 前景遮挡主体、主体遮挡背景、无遮挡 | 用「A 遮住 B 的哪一部分」描述 |
| 透视 | 一点/两点/三点透视、俯视灭点、广角畸变 | 融合多图时先统一灭点与地平线 |
| 相对尺度 | 主体约占画面高度 1/2、1/3；与参照物等高 | 给比例而非「很大」「很小」 |
| 画面朝向 | 人物朝画面右侧行走、视线看向画外 | 与留白方向一起写 |

Muse Image 要求把关系单独结构化到 `spatial_relationships`，每项以类型开头（细则见 `muse_image_rules.md` 第三节）：

| 类型 | 写法示例 |
|---|---|
| `position` | `position：机器人位于画面中央偏左` |
| `direction` | `direction：人物面向右侧的汽车` |
| `distance` | `distance：前景人物与背景建筑相距约一个街区` |
| `interaction` | `interaction：右手握住剑柄` |
| `occlusion` | `occlusion：桌角遮住人物左腿` |
| `containment` | `containment：钥匙在玻璃瓶内` |
| `alignment` | `alignment：三块招牌沿水平线对齐` |
| `scale` | `scale：人物高度约为门框的三分之二` |
| `depth` | `depth：人物清晰，远处建筑轻微虚化` |
| `attachment` | `attachment：徽章固定在左胸位置` |

### 11.2 材质与表面（material）

| 类别 | 术语 | 描述要点 |
|---|---|---|
| 硬质 | 金属 `metal` / 玻璃 `glass` / 石材 / 陶瓷 / 混凝土 | 反射强弱、粗糙度、边缘高光 |
| 软质 | 织物 `fabric` / 皮革 `leather` / 羽毛 / 毛发 | 纹理走向、褶皱、蓬松度 |
| 透明/半透明 | 透明伞面、磨砂玻璃、薄纱 | 透光率、折射、挂水珠 |
| 自然 | 水面 / 雾气 / 泥土 / 木纹 / 植被 | 湿度、颗粒、风化痕迹 |
| 表面状态 | 湿润 `wet` / 干燥 / 磨损 `worn` / 抛光 `polished` / 哑光 `matte` / 生锈 `rusty` | 一句话写「状态 + 反光 + 污渍」 |

### 11.3 编辑与复刻约束

| 字段 | 写法 | 示例 |
|---|---|---|
| `modification_scope` | 只写允许改动的对象，一次一件事 | `["仅替换背景灯牌内容"]` |
| `preserve_constraints` | 写「必须不变」的可识别特征 | `["人物姿态与服装", "街道材质与反光"]` |
| `forbidden_changes` | 写「禁止发生」的位移/身份/结构变化 | `["不改变镜头焦段", "不新增画面文字"]` |

GPT Image 把负向约束拆成三类自然语言句子，写进 Constraints 段（不要整段照搬 negative words）：

1. **排除**：`Do not include watermarks, unwanted text, additional people or unrelated objects.`
2. **保留**：`Keep the original facial features, expression, pose and body proportions unchanged.`
3. **修改边界**：`Only modify the clothing and background. Do not change the character or camera framing.`

复刻（recreate）时额外写「Do not invent details that are not visible in the reference」，并避免添加参考图中没有的风格词。

## 十二、参考图角色对照

与 `prompt_framework.md` 2.3.3 的角色枚举一一对应；每张图只定一个角色，一行一张写进 `reference_images`：

| 角色枚举 | 中文 | 提取内容 | 禁止迁移 |
|---|---|---|---|
| `edit_target` | 编辑原图 | 原画面全部信息 + 修改位置 | — |
| `identity_reference` | 身份参考 | 面部、发型、肤色、体型 | 服装、姿势、背景 |
| `pose_reference` | 姿态参考 | 肢体角度、手势、朝向 | 面部身份、服装细节 |
| `clothing_reference` | 服装参考 | 款式、颜色、材质、配饰 | 人物身份、背景 |
| `style_reference` | 风格参考 | 画风、配色、光影质感 | 具体人物与构图 |
| `composition_reference` | 构图参考 | 视角、景别、元素位置 | 主体身份、画风 |
| `background_reference` | 背景参考 | 地点、环境元素、时间氛围 | 人物与前景道具 |
| `object_reference` | 道具参考 | 外形、材质、标识细节 | 人物、场景风格 |

Muse Image 资料里的 `subject_reference` 不新增枚举：人物主体用 `identity_reference`，非人物主体/道具用 `object_reference`；同一张图的「用途 / 保留 / 禁止迁移」写在同一条 `图N：` 里。

写法：`图1：identity_reference；提取：面部与发型；保留：构图；禁止迁移：服装；优先级：主参考`。多图共用角色时用「优先级」区分主次；角色无法判断时先询问用户，或写入 `uncertainty` 的 `unknown:` 项。
