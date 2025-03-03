import aiohttp
import asyncio
import base64
import re
import json
from io import BytesIO
from PIL import Image
from pathlib import Path
from opencc import OpenCC

SRC_PATH = Path(__file__).parent / "src"
CARD_PATH = Path(__file__).parent / "src/card.jpg"
CARD_NAME = "card.jpg"

# 原始dc卡片参考分辨率，from example_card_2.png
REF_WIDTH = 1072
REF_HEIGHT = 602
    
# 裁切区域比例（左、上、右、下），数字来自src/example_card_2.png
# 技能树扫描顺序：普攻、共鸣技能、共鸣解放、变奏技能、共鸣回路(json_skillList顺序)
crop_ratios = [
    (  0/REF_WIDTH,   0/REF_HEIGHT, 420/REF_WIDTH, 350/REF_HEIGHT), # 角色
    (583/REF_WIDTH,  30/REF_HEIGHT, 653/REF_WIDTH, 130/REF_HEIGHT), # 普攻
    (456/REF_WIDTH, 115/REF_HEIGHT, 526/REF_WIDTH, 215/REF_HEIGHT), # 共鸣技能
    (694/REF_WIDTH, 115/REF_HEIGHT, 764/REF_WIDTH, 215/REF_HEIGHT), # 共鸣解放
    (650/REF_WIDTH, 250/REF_HEIGHT, 720/REF_WIDTH, 350/REF_HEIGHT), # 变奏技能
    (501/REF_WIDTH, 250/REF_HEIGHT, 571/REF_WIDTH, 350/REF_HEIGHT), # 共鸣回路
    ( 10/REF_WIDTH, 360/REF_HEIGHT, 214/REF_WIDTH, 590/REF_HEIGHT), # 声骸1
    (221/REF_WIDTH, 360/REF_HEIGHT, 425/REF_WIDTH, 590/REF_HEIGHT), # 声骸2
    (430/REF_WIDTH, 360/REF_HEIGHT, 634/REF_WIDTH, 590/REF_HEIGHT), # 声骸3
    (639/REF_WIDTH, 360/REF_HEIGHT, 843/REF_WIDTH, 590/REF_HEIGHT), # 声骸4
    (848/REF_WIDTH, 360/REF_HEIGHT, 1052/REF_WIDTH, 590/REF_HEIGHT), # 声骸5
    (800/REF_WIDTH, 240/REF_HEIGHT, 1020/REF_WIDTH, 350/REF_HEIGHT), # 武器
]

# 原始声骸裁切区域参考分辨率，from crop_ratios
ECHO_WIDTH = 204
ECHO_HEIGHT = 230

echo_crop_ratios = [
    (110/ECHO_WIDTH,  40/ECHO_HEIGHT, 204/ECHO_WIDTH,  85/ECHO_HEIGHT), # 右上角主词条(忽略声骸cost，暂不处理)
    ( 26/ECHO_WIDTH, 105/ECHO_HEIGHT, 204/ECHO_WIDTH, 230/ECHO_HEIGHT), # 下部6条副词条
]


def cut_image(image, img_width, img_height, crop_ratios):
    # 裁切图片
    cropped_images = []
    for ratio in crop_ratios:
        # 根据相对比例计算实际裁切坐标
        left = ratio[0] * img_width
        top = ratio[1] * img_height
        right = ratio[2] * img_width
        bottom = ratio[3] * img_height
        
        # 四舍五入取整并确保不越界
        left = max(0, int(round(left)))
        top = max(0, int(round(top)))
        right = min(img_width, int(round(right)))
        bottom = min(img_height, int(round(bottom)))
        
        # 执行裁切
        cropped_image = image.crop((left, top, right, bottom))
        cropped_images.append(cropped_image)

    return cropped_images

def cut_echo_data_ocr(image_echo):
    """
    裁切声骸卡片拼接词条数据: 右上角主词条与余下6条副词条
    目的: 优化ocrspace 模型2识别
    """
    img_width, img_height = image_echo.size
    
    # 获取裁切后的子图列表
    cropped_images = cut_image(image_echo, img_width, img_height, echo_crop_ratios)

    # 计算拼接后图片的总高度和最大宽度
    total_height = sum(img.height for img in cropped_images)
    max_width = max(img.width for img in cropped_images) if cropped_images else 0

    # 创建新画布并逐个粘贴子图
    image_echo_only_data = Image.new('RGB', (max_width, total_height))
    y_offset = 0
    for img in cropped_images:
        image_echo_only_data.paste(img, (0, y_offset))
        y_offset += img.height  # 累加y轴偏移量

    return image_echo_only_data

async def cut_card_ocr():
    """
    裁切卡片：角色，技能树*5，声骸*5，武器
        （按比例适配任意分辨率，1920*1080识别效果优良）
    """

    # 打开图片
    image = Image.open(CARD_PATH).convert('RGB')
    img_width, img_height = image.size  # 获取实际分辨率
    
    cropped_images = cut_image(image, img_width, img_height, crop_ratios)

    # 进一步裁剪拼接声骸图
    for i in range(6, 11):  # 替换索引6-10，即5张声骸图
        image_echo = cropped_images[i]
        cropped_images[i] = cut_echo_data_ocr(image_echo) 

    for i, cropped_image in enumerate(cropped_images):
        # 保存裁切后的图片
        cropped_image.save(f"{SRC_PATH}/_{i}.png")
    
    return cropped_images

async def card_part_ocr(cropped_images):
    """
    使用 OCR.space 免费API识别碎块图片
    """
    API_KEY = 'your_key'  # 请替换为你的API密钥
    API_URL = 'https://api.ocr.space/parse/image'
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for img in cropped_images:
            # 将PIL.Image转换为base64
            try:
                buffered = BytesIO()
                img.save(buffered, format='PNG')
                img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            except Exception as e:
                print(f"图像转换错误: {e}")
                continue
                
            # 构建请求参数
            payload = {
                'apikey': API_KEY,
                'language': 'cht',          # 仅繁体中文（正确参数值）
                'isOverlayRequired': 'True', # 需要坐标信息
                'base64Image': f'data:image/png;base64,{img_base64}',
                'OCREngine': 2,             # 使用引擎2, 识别效果更好，声骸识别差一些
                'isTable': 'True',    # 启用表格识别模式
                'detectOrientation': 'True', # 自动检测方向
                'scale': 'True'              # 图像缩放增强
            }

            tasks.append(fetch_ocr_result(session, API_URL, payload))

        # 限制并发数为5防止超过API限制
        semaphore = asyncio.Semaphore(5)
        # 修改返回结果处理
        results = await asyncio.gather(*(process_with_semaphore(task, semaphore) for task in tasks))
        
        # 扁平化处理（合并所有子列表）
        return [item for sublist in results for item in sublist]

async def process_with_semaphore(task, semaphore):
    async with semaphore:
        return await task

async def fetch_ocr_result(session, url, payload, retries=3):
    """发送OCR请求并处理响应, 错误重试次数: retries=3"""
    for attempt in range(retries):
        try:
            async with session.post(url, data=payload) as response:
                # 检查HTTP状态码
                if response.status != 200:
                    # 修改错误返回格式为字典（与其他成功结果结构一致）
                    return [{'error': f'HTTP Error {response.status}', 'text': None}]
                
                data = await response.json()
                
                # 检查API错误
                if data.get('IsErroredOnProcessing', False):
                    return [{'error': data.get('ErrorMessage', '未知错误'), 'text': None}]
                
                # 解析结果
                if not data.get('ParsedResults'):
                    return [{'error': 'No Results', 'text': None}]
                
                output = []
                
                # 提取识别结果
                for result in data.get('ParsedResults', []):
                    # 补充完整文本
                    if parsed_text := result.get('ParsedText'):
                        output.append({
                            'text': parsed_text,
                            'error': None  # 统一数据结构
                        })
                
                return output
                
        except aiohttp.ClientError as e:
            if attempt < retries - 1:
                await asyncio.sleep(2**attempt)
                continue
            return [{'error': f'Network Error:{str(e)}', 'text': None}]
        except Exception as e:
            if attempt < retries - 1:
                await asyncio.sleep(2**attempt)
                continue
            return [{'error': f'Processing Error:{str(e)}', 'text': None}]


def ocr_results_to_dict(ocr_results):
    """
    适配OCR.space输出结构的增强版结果解析
    输入结构: [{'text': '...', 'error': ...}, ...]
    """
    final_result = {
        "用户信息": {},
        "角色信息": {},
        "技能等级": [],
        "装备数据": [],
        "武器信息": {}
    }

    # 增强正则模式（适配多行文本处理）
    patterns = {
        "name": re.compile(r'^([\u4e00-\u9fa5A-Za-z]+)'), # 支持英文名，为后续逻辑判断用
        "level": re.compile(r'(?i)(LV?\.?)\s*(\d+)'),
        "skill_level": re.compile(r'(\d+)/10'),
        "player_info": re.compile(r'玩家名稱[:：]\s*(\S+)'),
        "uid_info": re.compile(r'特徵碼[:：]\s*(\d+)'),
        "echo_value": re.compile(r'([\u4e00-\u9fa5]+)\s*\D*([\d.]+%?)'), # 不支持英文词条(空格不好处理), 支持处理"暴擊傷害 器44%", "攻擊 ×18%"
        "weapon_info": re.compile(r'([\u4e00-\u9fa5]+)\s+LV\.(\d+)')
    }

    cc = OpenCC('t2s')  # 繁体转简体

    # 处理角色信息（第一个识别结果）
    if ocr_results:
        first_result = ocr_results[0]
        if first_result['error'] is None:
            lines = first_result['text'].split('\t')
            # lines = [row.split('\t') for row in words] # 再对每一行按 \t 分隔
            for line in lines:
                # 文本预处理：去除多余的空白符
                line_clean = re.sub(r'\s+', ' ', line).strip()  # 使用 \s+ 匹配所有空白符，并替换为单个空格
                # line_clean = line.strip()

                # 角色名提取
                if not final_result["角色信息"].get("角色名"):
                    name_match = patterns["name"].search(line_clean)
                    if name_match:
                        print(f" [鸣潮][dc卡片识别] 识别出角色名:{name_match.group()}")
                        if not re.match(r'^[\u4e00-\u9fa5]+$', name_match.group()):
                            print(f" [鸣潮][dc卡片识别] 识别出英文角色名:{name_match.group()}")
                            return False, final_result
                        final_result["角色信息"]["角色名"] = cc.convert(name_match.group())

                # 等级提取
                level_match = patterns["level"].search(line_clean)
                if level_match and not final_result["角色信息"].get("等级"):
                    final_result["角色信息"]["等级"] = int(level_match.group(2))

                # 玩家名称
                player_match = patterns["player_info"].search(line_clean)
                if player_match:
                    final_result["用户信息"]["玩家名称"] = player_match.group(1)

                # UID提取
                uid_match = patterns["uid_info"].search(line_clean)
                if uid_match:
                    final_result["用户信息"]["UID"] = uid_match.group(1)

    # 处理技能等级（第2-6个结果）
    for idx in range(1, 6):
        if idx >= len(ocr_results) or ocr_results[idx]['error'] is not None:
            final_result["技能等级"].append(1)
            continue
            
        text = ocr_results[idx]['text']
        matches = patterns["skill_level"].findall(text)
        if matches:
            try:
                level = int(matches[0])
                final_result["技能等级"].append(min(level, 10))  # 限制最大等级为10
            except:
                final_result["技能等级"].append(1)
        else:
            final_result["技能等级"].append(1)

    # 处理声骸装备（第7-11个结果）
    for idx in range(6, 11):
        if idx >= len(ocr_results) or ocr_results[idx]['error'] is not None:
            continue
            
        equipment = {"mainProps": [], "subProps": []}
        text = ocr_results[idx]['text']
        
        # 文本预处理：去除多余的空白符
        text_clean = re.sub(r'\s+', ' ', text).strip()  # 使用 \s+ 匹配所有空白符，并替换为单个空格

        # 提取属性对
        matches = patterns["echo_value"].findall(text_clean)
        valid_entries = []
        for attr, value in matches:
            # 属性清洗
            clean_attr = cc.convert(attr.strip())
            # 验证属性名是否符合预期（至少两个中文字符，且不含数字）
            if len(clean_attr) >= 2 and not re.search(r'[0-9]', clean_attr):
                valid_entries.append((clean_attr, value))
        
        # 分配主副属性
        if valid_entries:
             # 主词条逻辑（取前两个有效词条）
            for entry in valid_entries[:2]:
                equipment["mainProps"].append({
                    "attributeName": entry[0],
                    "attributeValue": entry[1],
                    "iconUrl": "" 
                })
            
            # 副词条逻辑（取接下来5个有效词条）
            for entry in valid_entries[2:7]:
                equipment["subProps"].append({
                    "attributeName": entry[0],
                    "attributeValue": entry[1]
                })
            
            final_result["装备数据"].append(equipment)

    # 处理武器信息（最后一个结果）
    if len(ocr_results) > 11 and ocr_results[11]['error'] is None:
        text = ocr_results[11]['text']
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # 武器名称（取第一行有效文本）
        for line in lines:
            if patterns["name"].search(line):
                final_result["武器信息"]["武器名"] = cc.convert(line)
                break
                
        # 武器等级
        for line in lines:
            level_match = patterns["level"].search(line)
            if level_match:
                final_result["武器信息"]["等级"] = int(level_match.group(2))
                break

    print(f" [鸣潮][dc卡片识别] 最终提取内容:\n{json.dumps(final_result, indent=2, ensure_ascii=False)}")
    return True, final_result

# 使用示例
async def main():
    # ocr识别提取部分
    # cropped_images = await cut_card_ocr()
    # # 假设 cropped_images 是包含PIL.Image对象的列表
    # results = await card_part_ocr(cropped_images)
    # # print(results)
    
    # if results:
    #     for i, item in enumerate(results):
    #         print(f"识别结果 {i+1}:")
    #         print(f"文本内容: \n{item['text']}")
    #         print(f"error内容: \n{item['error']}")
    #         print("-" * 30)

    # 识别数据处理部分
    result = [{'text': '◎\tCarlotta\tLV.90\t\r\nPlayer ID:lnnocent\t\r\nUID:700590032\t\r\n', 'error': None}, {'text': 'LV.7/10\t\r\n', 'error': None}, {'text': 'LV.9/10\t\r\n', 'error': None}, {'text': 'LV.10/10\t\r\n', 'error': None}, {'text': 'LV.10/10\t\r\n', 'error': None}, {'text': 'LV.5/10\t\r\n', 'error': None}, {'text': 'Crit. Rate\t\r\n#22%\t\r\nATK\t150\t\r\nCrit. DMG\t12.6%\t\r\nResonance Skill DMG\t7.9%\t\r\nPpTus\t7.9%\t\r\nEnergy Regen\t8.4%\t\r\nCrit.Rate\t8.7%\t\r\n', 'error': None}, {'text': 'Glacio DMG Bonus\t\r\n30%\t\r\nATK\t100\t\r\nATK\t8.6%\t\r\nCrit. Rate\t7.5%\t\r\nResonance Skill DMG\t10.1%6\t\r\nBonus\t\r\nHeavy Attack DMG Bonus\t7.9%\t\r\nCrit.DMG\t21%6\t\r\n', 'error': None}, {'text': 'Glacio DMG Bonus\t\r\n30%\t\r\nATK\t100\t\r\nDEF\t60\t\r\nCrit. DMG\t18.6%\t\r\nResonance Liberation\t8.6%\t\r\nDMG onus\t\r\nCrit. Rate\t9.9%\t\r\nHeavy Attack DMG Bonus\t10.9%6\t\r\n', 'error': None}, {'text': 'ATK\t\r\n×18%\t\r\nHP\t2280.\t\r\nDEF\t60\t\r\nResonance Skill DMG\t9.4%\t\r\nERR MG\t17.4%\t\r\nCrit. Rate\t7.5%\t\r\nHP\t9.4%\t\r\n', 'error': None}, {'text': 'ATK\t\r\n×18%\t\r\nHP\t2280\t\r\nHeavy Attack DMG Bonus\t10.9%6\t\r\nCrit. Rate\t9.3%\t\r\nCrit. DMG\t15%\t\r\nATK\t9.4%6\t\r\nHP\t4770\t\r\n', 'error': None}, {'text': 'The Last Dance\t\r\nLV.90\t\r\nAscension Level\t\r\n', 'error': None}]
    result_a = [{'text': '◎\t洛可可\tLV.90\t\r\n玩家名稱：橘子汽水\t\r\n特徵碼：711745893\t\r\n', 'error': None}, {'text': 'LV.6/10\t\r\n', 'error': None}, {'text': 'LV.6/10\t\r\n', 'error': None}, {'text': 'LV.9/10\t\r\n', 'error': None}, {'text': 'LV.10/10\t\r\n', 'error': None}, {'text': 'LV.6/10\t\r\n', 'error': None}, {'text': '暴擊\t\r\n*22%\t\r\n攻擊\t150\t\r\n攻擊\t40\t\r\n攻擊\t9.4%\t\r\n生命\t11.6%\t\r\n暴擊\t6.9%\t\r\n暴擊傷害\t21%\t\r\n', 'error': None}, {'text': '暴擊傷害\t\r\n器44%\t\r\n攻擊\t150\t\r\n攻擊\t9.4%\t\r\n共鳴效率\t11.6%\t\r\n暴擊\t6.3%\t\r\n暴擊傷害\t12.6%\t\r\n攻擊\t50\t\r\n', 'error': None}, {'text': '攻擊\t\r\n×18%\t\r\n生命\t2280\t\r\n防禦\t12.8%\t\r\n暴擊\t7.5%\t\r\n暴擊傷害\t17.4%\t\r\n攻擊\t8.6%\t\r\n攻擊\t40\t\r\n', 'error': None}, {'text': '攻擊\t\r\n×18%\t\r\n生命\t2280\t\r\n暴擊傷害\t18.6%\t\r\n共鳴效率\t8.4%\t\r\n防禦\t60\t\r\n攻擊\t50\t\r\n暴擊\t7.5%\t\r\n', 'error': None}, {'text': '攻擊\t\r\n×18%\t\r\n生命\t2280\t\r\n攻擊\t9.4%\t\r\n普攻傷害加成\t8.6%\t\r\n暴擊傷害\t21%\t\r\n防禦\t50\t\r\n暴擎\t6.3%\t\r\n', 'error': None}, {'text': '悲喜劇\t\r\nLV.90\t\r\n突破等級\t\r\n', 'error': None}]
    ocr_results_to_dict(result)


if __name__ == '__main__':
    asyncio.run(main())