# 示例输出：Muse Image 专项（多参考图融合 + 空间关系）

> 本文件由 `python tools/gen_examples.py` 从 `tools/fixtures/semantic_muse_image.json` 生成，请勿手工编辑。

## Prompt 编译结果

- 模态：`image`
- 目标模型：`muse_image`
- 安全过滤：通过
- 注入标记：无

## Prompt 列表

### Muse Image 1.0（v1.0） · compose

```text
Compose a new image from the provided reference images.

Element sources — each reference contributes only what is described:
图1：identity_reference；用途：只提取机器人头部轮廓、胸口核心位置与整体装甲比例；保留：机身材质与配色；禁止迁移：原图背景、原图光照；优先级：最高
图2：pose_reference；用途：只提取站姿、右手持剑角度与左肩朝向；保留：关节比例；禁止迁移：人物服装与面部特征；优先级：高
图3：background_reference；用途：只提取高炉、管道结构与蒸汽分布；保留：工业空间层次；禁止迁移：原图人物与前景平台；优先级：中

Reference usage: 图1 只负责角色身份与装甲设计，不携带原图场景、图2 只负责姿态与持剑方向，不改变角色外观、图3 只负责背景工业结构与蒸汽，不引入原图人物
Allowed feature transfer: 图1：头部窄缝发光眼、胸口蓝色核心、黑金属装甲比例、图2：站姿、右手握剑角度、左肩朝向、图3：高炉轮廓、管道走向、蒸汽层次
Forbidden feature transfer: 图1：不得迁移原图背景与暖色光照、图2：不得迁移原图人物服装与面部、图3：不得迁移原图人物与前景平台

Primary subject: 一名穿黑色机甲装甲的人形机器人，胸口有蓝色能量核心，头部为窄缝式发光眼
Placement and scale: 画面中央偏左，双脚踩在积水金属平台上，身体朝向画面右前方. 机器人约占画面高度三分之二，明显高于背景管道
Spatial relationships: 机器人位于前景平台，长剑伸向右下方，背景高炉在其左后方，蒸汽从右侧管道喷出. position：机器人位于画面中央偏左，站立于前景金属平台、direction：机器人面朝右前方，长剑剑尖指向右下方、distance：机器人与背景高炉之间隔着一层蒸汽，约有一个平台宽度的纵深、interaction：右手握住长剑剑柄，左手自然下垂、occlusion：右肩装甲遮住身后的一段管道、containment：蓝色能量核心嵌在胸口装甲内部、alignment：高炉与右侧管道沿画面右上到左下形成斜线、scale：机器人高度约为背景高炉入口的三倍、depth：机器人清晰，背景蒸汽与高炉轻微虚化、attachment：左肩挂载一块矩形装甲板
Composition: 三分法构图，机器人压在左三分线，长剑与右侧蒸汽形成对角引导线
Visual style: 写实科幻电影概念设计，高细节，体积光. Lighting: 冷蓝主光从左上打下，右侧蒸汽后方有暖橙逆光，湿金属表面出现条状高光. Color: 深蓝与青灰为主，蓝色能量核心与暖橙逆光形成强调色. Material: 哑光黑金属装甲带磨损划痕，湿滑钢板地面，半透明蒸汽.
Aspect ratio: 16:9
Constraints: integrate all referenced elements into one coherent scene; match perspective, light direction, color temperature and material across elements; do not simply collage or paste the references; preserve the identity and proportions of the primary subject.
```

## 评分报告

| 维度 | 权重 | 得分 | 依据 |
|---|---:|---:|---|
| 主题明确度 | 20% | 85 | — |
| 场景完整度 | 20% | 95 | — |
| 风格契合度 | 20% | 80 | — |
| 结构清晰度 | 15% | 60 | — |
| 参数合理性 | 15% | 60 | — |
| 可调性/复用性 | 10% | 60 | — |

总分：76.0 / 100（等级 B）
（自动启发式近似评分，仅供参考）
优化建议 1：把具体样例中的可变项替换为 [变量] 占位
优化建议 2：对照 model_mappings.md 核对参数语法与取值范围

## Muse Image 审查清单（不参与总分）

| 检查项 | 结论 | 说明 |
|---|---|---|
| 任务目标与主体是否齐全 | 通过 | 任务必填字段与主体齐全 |
| 空间关系是否逐条明确 | 通过 | 已提供 spatial_relationships |
| 参考图角色与迁移边界是否清楚 | 通过 | 3 张参考图角色与迁移边界已写明 |
| 修改目标与保留边界是否完整 | 通过 | 非编辑任务 |
| 系列/多轮一致性能否继承 | 通过 | 非系列/多轮任务 |
| 文字内容与版式层级是否明确 | 通过 | 无画内文字 |
