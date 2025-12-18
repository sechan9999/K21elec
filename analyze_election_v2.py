#!/usr/bin/env python3
"""
21대 대선 개표상황표 분석 스크립트 v2
더 정확한 OCR 추출을 위한 개선된 버전
"""

import fitz  # PyMuPDF
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import io
import re
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
import sys

# 대상 후보자
TARGET_CANDIDATES = ["이재명", "김문수", "이준석", "권영국", "송진호"]

@dataclass
class CandidateVote:
    name: str
    classified: int = 0  # 분류된 투표지
    reconfirm: int = 0   # 재확인대상 투표지
    total: int = 0       # 계

@dataclass
class PageData:
    page_num: int
    district: str = ""
    voting_type: str = ""
    candidates: List[CandidateVote] = field(default_factory=list)
    valid_votes: int = 0
    invalid_votes: int = 0
    total_votes: int = 0


def preprocess_image(img: Image.Image) -> Image.Image:
    """이미지 전처리로 OCR 품질 향상"""
    # 그레이스케일 변환
    img = img.convert('L')
    # 대비 향상
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2.0)
    # 샤프닝
    img = img.filter(ImageFilter.SHARPEN)
    return img


def clean_number(text: str) -> int:
    """숫자 문자열 정리"""
    if not text:
        return 0
    # OCR 오류 수정: 마침표를 콤마로 간주
    text = text.replace('.', '')
    # 숫자만 추출
    cleaned = re.sub(r'[^\d]', '', str(text))
    return int(cleaned) if cleaned else 0


def extract_all_numbers(text: str) -> List[int]:
    """텍스트에서 모든 숫자 추출 (3자리 이상만)"""
    # 숫자 패턴: 콤마/마침표 포함 가능
    numbers = re.findall(r'\d[\d,\.]*\d|\d', text)
    result = []
    for n in numbers:
        val = clean_number(n)
        if val >= 1:  # 최소 1 이상
            result.append(val)
    return result


def parse_candidate_line(line: str, candidate: str) -> Tuple[int, int, int]:
    """후보자 라인에서 숫자 추출"""
    # 후보자명 이후의 숫자들만 추출
    idx = line.find(candidate)
    if idx == -1:
        return 0, 0, 0

    after = line[idx + len(candidate):]
    numbers = extract_all_numbers(after)

    if not numbers:
        return 0, 0, 0

    # 숫자가 3개 이상이면 분류, 재확인, 계 순서로 추출
    # 일반적으로: 분류 > 계 > 재확인 (크기 순)
    if len(numbers) >= 3:
        # 가장 큰 숫자 3개 선택
        sorted_nums = sorted(numbers, reverse=True)[:3]
        # 계 = 가장 큰 숫자
        total = sorted_nums[0]
        # 분류 = 두 번째로 큰 숫자
        classified = sorted_nums[1]
        # 재확인 = 세 번째로 큰 숫자
        reconfirm = sorted_nums[2] if len(sorted_nums) > 2 else 0

        # 검증: classified + reconfirm ≈ total
        if abs((classified + reconfirm) - total) <= total * 0.1:
            return classified, reconfirm, total
        else:
            # 다른 조합 시도
            for i, n1 in enumerate(numbers):
                for j, n2 in enumerate(numbers):
                    if i != j:
                        for k, n3 in enumerate(numbers):
                            if k != i and k != j and n1 + n2 == n3:
                                return n1, n2, n3

    elif len(numbers) == 2:
        return max(numbers), min(numbers), sum(numbers)
    elif len(numbers) == 1:
        return numbers[0], 0, numbers[0]

    return 0, 0, 0


def process_page_v2(doc, page_num: int, verbose: bool = False) -> Optional[PageData]:
    """단일 페이지 처리 (개선 버전)"""
    try:
        page = doc[page_num]

        # 고해상도로 이미지 변환
        mat = fitz.Matrix(3, 3)  # 3x 확대
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))

        # 이미지 전처리
        img = preprocess_image(img)

        # OCR 실행
        custom_config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
        text = pytesseract.image_to_string(img, lang='kor+eng', config=custom_config)

        if verbose:
            print(f"\n{'='*60}")
            print(f"Page {page_num + 1}:")
            print(text[:1500])

        # 데이터 추출
        data = PageData(page_num=page_num + 1)

        # 투표구 추출
        for pattern in [r'대통령선거\s*(\S+읍)', r'대통령선거\s*(\S+면)', r'대통령선거\s*(\S+동)']:
            match = re.search(pattern, text)
            if match:
                data.district = re.sub(r'[\[\]|]', '', match.group(1))
                break

        if not data.district:
            data.district = f"투표구_{page_num + 1}"

        # 투표유형 추출
        if '관내사전' in text:
            data.voting_type = "관내사전"
        elif '선거일' in text:
            data.voting_type = "선거일"
        elif '관외사전' in text:
            data.voting_type = "관외사전"
        elif '재외' in text:
            data.voting_type = "재외투표"
        else:
            # 페이지 기반 추정
            if page_num < 26:
                data.voting_type = "관내사전"
            elif page_num < 168:
                data.voting_type = "선거일"
            else:
                data.voting_type = "기타"

        # 후보자별 득표 추출
        lines = text.split('\n')
        for target in TARGET_CANDIDATES:
            classified, reconfirm, total = 0, 0, 0

            for line in lines:
                if target in line:
                    classified, reconfirm, total = parse_candidate_line(line, target)
                    if total > 0:
                        break

            data.candidates.append(CandidateVote(
                name=target,
                classified=classified,
                reconfirm=reconfirm,
                total=total
            ))

        # 총계/유효/무효 추출
        for line in lines:
            if line.strip().startswith('계') or '계\t' in line:
                numbers = extract_all_numbers(line)
                if numbers:
                    sorted_nums = sorted(numbers, reverse=True)
                    data.total_votes = sorted_nums[0]
                    data.valid_votes = sorted_nums[1] if len(sorted_nums) > 1 else sorted_nums[0]

            if '무효' in line:
                numbers = extract_all_numbers(line)
                if numbers:
                    data.invalid_votes = min(numbers)

        return data

    except Exception as e:
        print(f"\nError page {page_num + 1}: {e}")
        return None


def analyze_pdf_v2(pdf_path: str, start: int = 0, end: int = None, verbose: bool = False) -> List[PageData]:
    """PDF 분석 (개선 버전)"""
    doc = fitz.open(pdf_path)
    total = len(doc)
    end = end or total

    print(f"📄 PDF: {pdf_path}")
    print(f"📝 페이지: {start + 1} ~ {end} (총 {total}페이지)")
    print("-" * 50)

    results = []
    for i in range(start, min(end, total)):
        pct = (i - start + 1) * 100 // (end - start)
        print(f"\r⏳ 처리: {i + 1}/{end} ({pct}%)", end="", flush=True)

        data = process_page_v2(doc, i, verbose)
        if data:
            results.append(data)

    print(f"\n✅ 완료: {len(results)}개 페이지")
    doc.close()
    return results


def to_dataframe(results: List[PageData], candidates: List[str] = None) -> pd.DataFrame:
    """DataFrame 변환"""
    candidates = candidates or TARGET_CANDIDATES

    rows = []
    for d in results:
        row = {
            '페이지': d.page_num,
            '투표구': d.district,
            '유형': d.voting_type,
            '유효투표': d.valid_votes,
            '무효투표': d.invalid_votes,
            '총계': d.total_votes,
        }
        for c in d.candidates:
            if c.name in candidates:
                row[f'{c.name}_분류'] = c.classified
                row[f'{c.name}_재확인'] = c.reconfirm
                row[f'{c.name}_계'] = c.total
        rows.append(row)

    return pd.DataFrame(rows)


def print_summary(df: pd.DataFrame, candidates: List[str] = None):
    """요약 출력"""
    candidates = candidates or TARGET_CANDIDATES

    print("\n" + "=" * 70)
    print("📊 21대 대선 개표 감사 결과")
    print("=" * 70)

    print(f"\n📌 분석 페이지: {len(df)}")
    print(f"📌 총 유효투표: {df['유효투표'].sum():,}")
    print(f"📌 총 무효투표: {df['무효투표'].sum():,}")
    print(f"📌 총 투표수: {df['총계'].sum():,}")

    print("\n" + "-" * 70)
    print("🗳️  후보자별 득표 현황 (심사·집계부)")
    print("-" * 70)
    print(f"{'후보자':<10} {'분류된 투표지':>15} {'재확인대상':>12} {'총계':>12} {'재확인율':>10}")
    print("-" * 70)

    for c in candidates:
        if f'{c}_계' in df.columns:
            classified = df[f'{c}_분류'].sum()
            reconfirm = df[f'{c}_재확인'].sum()
            total = df[f'{c}_계'].sum()
            rate = (reconfirm / total * 100) if total > 0 else 0
            print(f"{c:<10} {classified:>15,} {reconfirm:>12,} {total:>12,} {rate:>9.2f}%")

    print("-" * 70)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='21대 대선 개표상황표 분석 v2')
    parser.add_argument('pdf', nargs='?', default='/home/user/K21elec/jeju.pdf')
    parser.add_argument('--start', type=int, default=0)
    parser.add_argument('--end', type=int, default=None)
    parser.add_argument('-o', '--output', default='election_result.csv')
    parser.add_argument('-c', '--candidates', nargs='+', default=None)
    parser.add_argument('-s', '--sample', type=int, default=None)
    parser.add_argument('-v', '--verbose', action='store_true')

    args = parser.parse_args()

    if args.sample:
        args.end = args.start + args.sample

    candidates = args.candidates or TARGET_CANDIDATES

    print("=" * 70)
    print("🗳️  21대 대선 개표상황표 분석 시스템 v2")
    print("    (Tesseract OCR - API 불필요)")
    print("=" * 70)
    print(f"📋 후보자: {', '.join(candidates)}\n")

    results = analyze_pdf_v2(args.pdf, args.start, args.end, args.verbose)

    if not results:
        print("❌ 데이터 없음")
        return

    df = to_dataframe(results, candidates)
    print_summary(df, candidates)

    # 저장
    df.to_csv(args.output, index=False, encoding='utf-8-sig')
    print(f"\n💾 저장: {args.output}")

    xlsx = args.output.replace('.csv', '.xlsx')
    try:
        df.to_excel(xlsx, index=False)
        print(f"💾 저장: {xlsx}")
    except:
        pass

    print("\n🎉 완료!")


if __name__ == '__main__':
    main()
