#!/usr/bin/env python3
"""
간단한 21대 대선 개표상황표 추출기
전체 텍스트에서 후보자 근처 숫자를 찾는 방식
"""

import fitz
import pytesseract
from PIL import Image, ImageEnhance
import io
import re
import pandas as pd
from collections import defaultdict

CANDIDATES = ["이재명", "김문수", "이준석", "권영국", "송진호"]


def extract_page(doc, page_num):
    """페이지에서 데이터 추출"""
    page = doc[page_num]

    # 고해상도 이미지
    mat = fitz.Matrix(3, 3)
    pix = page.get_pixmap(matrix=mat)
    img = Image.open(io.BytesIO(pix.tobytes("png")))

    # 전처리
    img = img.convert('L')
    img = ImageEnhance.Contrast(img).enhance(2.0)

    # OCR
    text = pytesseract.image_to_string(img, lang='kor+eng', config='--oem 3 --psm 6')

    # 투표구 추출
    district = ""
    for p in [r'대통령선거\s*(\S+읍)', r'대통령선거\s*(\S+면)', r'대통령선거\s*(\S+동)']:
        m = re.search(p, text)
        if m:
            district = re.sub(r'[\[\]|]', '', m.group(1))
            break

    if not district:
        district = f"page_{page_num + 1}"

    # 투표유형
    if '관내사전' in text:
        vtype = "관내사전"
    elif '선거일' in text:
        vtype = "선거일"
    elif '관외사전' in text:
        vtype = "관외사전"
    else:
        vtype = "관내사전" if page_num < 26 else "선거일"

    # 후보자별 득표 - 전체 텍스트에서 추출
    results = {'page': page_num + 1, 'district': district, 'type': vtype}

    # 숫자 클리닝 함수
    def clean(s):
        return int(re.sub(r'[^\d]', '', s) or 0)

    for candidate in CANDIDATES:
        # 후보자명 이후 100자 내의 숫자들 찾기
        pattern = rf'{candidate}[^\d]*(\d[\d,\.]*)[^\d]*(\d[\d,\.]*)?[^\d]*(\d[\d,\.]*)?'
        match = re.search(pattern, text, re.DOTALL)

        if match:
            nums = [clean(g) for g in match.groups() if g]
            nums = [n for n in nums if n > 0]

            if len(nums) >= 3:
                # 가장 큰 숫자가 총계일 가능성 높음
                sorted_nums = sorted(nums, reverse=True)
                total = sorted_nums[0]
                classified = sorted_nums[1] if len(sorted_nums) > 1 else 0
                reconfirm = sorted_nums[2] if len(sorted_nums) > 2 else 0
            elif len(nums) == 2:
                classified, reconfirm = max(nums), min(nums)
                total = classified + reconfirm
            elif len(nums) == 1:
                total = classified = nums[0]
                reconfirm = 0
            else:
                total = classified = reconfirm = 0
        else:
            total = classified = reconfirm = 0

        results[f'{candidate}_분류'] = classified
        results[f'{candidate}_재확인'] = reconfirm
        results[f'{candidate}_계'] = total

    # 총계 추출
    total_match = re.search(r'계[^\d]*(\d[\d,\.]*)[^\d]*(\d[\d,\.]*)[^\d]*(\d[\d,\.]*)', text)
    if total_match:
        nums = [clean(g) for g in total_match.groups() if g]
        results['valid'] = max(nums) if nums else 0
        results['total'] = max(nums) if nums else 0
    else:
        results['valid'] = 0
        results['total'] = 0

    # 무효
    invalid_match = re.search(r'무효[^\d]*(\d+)', text)
    results['invalid'] = clean(invalid_match.group(1)) if invalid_match else 0

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('pdf', nargs='?', default='/home/user/K21elec/jeju.pdf')
    parser.add_argument('-s', '--sample', type=int, default=None)
    parser.add_argument('-o', '--output', default='simple_result.csv')
    args = parser.parse_args()

    doc = fitz.open(args.pdf)
    total = len(doc)
    end = args.sample or total

    print(f"🗳️  21대 대선 개표 분석")
    print(f"📄 {args.pdf} ({total} pages)")
    print(f"📝 분석: 1~{end} 페이지")
    print("-" * 50)

    rows = []
    for i in range(end):
        print(f"\r⏳ {i+1}/{end} ({(i+1)*100//end}%)", end="", flush=True)
        rows.append(extract_page(doc, i))

    doc.close()
    df = pd.DataFrame(rows)

    # 요약
    print(f"\n\n{'='*60}")
    print("📊 결과 요약")
    print("="*60)

    for c in CANDIDATES:
        col = f'{c}_계'
        if col in df.columns:
            total = df[col].sum()
            classified = df[f'{c}_분류'].sum()
            reconfirm = df[f'{c}_재확인'].sum()
            rate = (reconfirm/total*100) if total > 0 else 0
            print(f"{c}: 분류 {classified:,} | 재확인 {reconfirm:,} | 계 {total:,} ({rate:.2f}%)")

    # 저장
    df.to_csv(args.output, index=False, encoding='utf-8-sig')
    print(f"\n💾 {args.output}")
    print("🎉 완료!")


if __name__ == '__main__':
    main()
