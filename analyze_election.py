#!/usr/bin/env python3
"""
21대 대선 개표상황표 분석 스크립트
로컬에서 Tesseract OCR을 사용하여 PDF를 분석합니다.
"""

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
import re
import pandas as pd
from dataclasses import dataclass
from typing import List, Optional, Tuple
import sys

# 대상 후보자
TARGET_CANDIDATES = ["이재명", "김문수", "이준석", "권영국", "송진호"]

# 후보자 이름 변형 (OCR 오류 대응)
CANDIDATE_ALIASES = {
    "이재명": ["이재명", "재명", "이재"],
    "김문수": ["김문수", "문수", "김문"],
    "이준석": ["이준석", "준석", "이준"],
    "권영국": ["권영국", "영국", "권영"],
    "송진호": ["송진호", "진호", "송진"],
}

@dataclass
class CandidateVote:
    name: str
    classified: int  # 분류된 투표지
    reconfirm: int   # 재확인대상 투표지
    total: int       # 계

@dataclass
class PageData:
    page_num: int
    district: str
    voting_type: str
    candidates: List[CandidateVote]
    valid_votes: int
    invalid_votes: int
    total_votes: int
    raw_text: str = ""


def clean_number(text: str) -> int:
    """숫자 문자열에서 숫자만 추출"""
    if not text:
        return 0
    # 콤마, 점, 공백 등 제거
    cleaned = re.sub(r'[^\d]', '', str(text))
    return int(cleaned) if cleaned else 0


def find_numbers_after_text(text: str, search_term: str, count: int = 3) -> List[int]:
    """텍스트 뒤에 나오는 숫자들을 찾음"""
    # 검색어 위치 찾기
    pattern = rf'{re.escape(search_term)}'
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return [0] * count

    # 검색어 이후의 텍스트에서 숫자 추출
    after_text = text[match.end():match.end() + 200]

    # 숫자 패턴: 연속된 숫자(콤마 포함)
    numbers = re.findall(r'[\d,\.]+', after_text)
    result = []
    for num in numbers[:count]:
        result.append(clean_number(num))

    # 부족한 경우 0으로 채움
    while len(result) < count:
        result.append(0)

    return result


def extract_district_and_type(text: str) -> Tuple[str, str]:
    """투표구명과 투표유형 추출"""
    district = ""
    voting_type = ""

    # 투표구명 추출 (다양한 패턴)
    district_patterns = [
        r'대통령선거\s*(\S+읍)',
        r'대통령선거\s*(\S+면)',
        r'대통령선거\s*(\S+동)',
        r'제21대\s*대통령선거\s*(\S+)',
    ]
    for pattern in district_patterns:
        match = re.search(pattern, text)
        if match:
            district = match.group(1).strip()
            # 불필요한 문자 제거
            district = re.sub(r'[\[\]|]', '', district)
            break

    # 투표유형 추출
    type_mapping = {
        '관내사전': ['관내사전', '[관내사전'],
        '선거일': ['선거일', '[선거일'],
        '관외사전': ['관외사전', '[관외사전'],
        '재외투표': ['재외', '재외투표'],
        '거소/선상': ['거소', '선상'],
    }

    for vtype, keywords in type_mapping.items():
        for keyword in keywords:
            if keyword in text:
                voting_type = vtype
                break
        if voting_type:
            break

    return district, voting_type


def extract_candidate_votes_improved(text: str) -> List[CandidateVote]:
    """향상된 후보자별 득표 추출"""
    candidates = []
    lines = text.split('\n')

    for target in TARGET_CANDIDATES:
        classified = 0
        reconfirm = 0
        total = 0

        # 해당 후보자를 포함하는 라인 찾기
        for i, line in enumerate(lines):
            if target in line:
                # 같은 라인에서 숫자 추출
                numbers = re.findall(r'[\d,]+', line)
                numbers = [clean_number(n) for n in numbers if clean_number(n) > 0]

                if len(numbers) >= 3:
                    # 첫 번째 큰 숫자가 분류된 투표지
                    # 가장 작은 숫자가 재확인
                    # 가장 큰 숫자가 총계
                    sorted_nums = sorted(numbers, reverse=True)
                    total = sorted_nums[0] if sorted_nums else 0
                    classified = sorted_nums[1] if len(sorted_nums) > 1 else 0
                    reconfirm = sorted_nums[-1] if len(sorted_nums) > 2 else 0

                    # 논리적 검증: total = classified + reconfirm
                    if classified + reconfirm != total and len(numbers) >= 3:
                        # 다른 조합 시도
                        for j in range(len(numbers)):
                            for k in range(len(numbers)):
                                if j != k and numbers[j] + numbers[k] in numbers:
                                    classified = numbers[j]
                                    reconfirm = numbers[k]
                                    total = numbers[j] + numbers[k]
                                    break
                elif len(numbers) == 2:
                    classified = numbers[0]
                    reconfirm = numbers[1]
                    total = classified + reconfirm
                elif len(numbers) == 1:
                    total = numbers[0]
                    classified = total

                break

        candidates.append(CandidateVote(
            name=target,
            classified=classified,
            reconfirm=reconfirm,
            total=total
        ))

    return candidates


def extract_totals_improved(text: str) -> Tuple[int, int, int]:
    """향상된 유효투표, 무효투표, 총계 추출"""
    valid_votes = 0
    invalid_votes = 0
    total_votes = 0

    lines = text.split('\n')

    for line in lines:
        # "계" 행 찾기 (후보자별 합계)
        if line.strip().startswith('계') or '계\t' in line or '계 ' in line[:10]:
            numbers = re.findall(r'[\d,]+', line)
            numbers = [clean_number(n) for n in numbers if clean_number(n) > 0]
            if len(numbers) >= 2:
                # 가장 큰 숫자가 총계
                sorted_nums = sorted(numbers, reverse=True)
                total_votes = sorted_nums[0]
                valid_votes = sorted_nums[1] if len(sorted_nums) > 1 else sorted_nums[0]

        # 무효투표수 찾기
        if '무효' in line:
            numbers = re.findall(r'[\d,]+', line)
            numbers = [clean_number(n) for n in numbers if clean_number(n) > 0]
            if numbers:
                invalid_votes = min(numbers)  # 무효는 보통 작은 수

    # 투표수 총계 (투표용지 교부수)
    if total_votes == 0:
        for line in lines:
            if '투표수' in line and '교부' not in line:
                numbers = re.findall(r'[\d,]+', line)
                numbers = [clean_number(n) for n in numbers if clean_number(n) > 0]
                if numbers:
                    total_votes = max(numbers)
                    break

    return valid_votes, invalid_votes, total_votes


def process_page(doc, page_num: int, verbose: bool = False) -> Optional[PageData]:
    """단일 페이지 처리"""
    try:
        page = doc[page_num]

        # 이미지로 변환 (고해상도)
        mat = fitz.Matrix(2.5, 2.5)  # 2.5x 확대
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))

        # OCR 실행 (한국어 + 영어)
        custom_config = r'--oem 3 --psm 6'
        text = pytesseract.image_to_string(img, lang='kor+eng', config=custom_config)

        if verbose:
            print(f"\n{'='*60}")
            print(f"Page {page_num + 1} OCR result:")
            print(text[:2000])
            print("...")

        # 데이터 추출
        district, voting_type = extract_district_and_type(text)
        candidates = extract_candidate_votes_improved(text)
        valid_votes, invalid_votes, total_votes = extract_totals_improved(text)

        # 기본 유형 설정 (페이지 번호 기반)
        if not voting_type:
            if page_num < 26:
                voting_type = "관내사전"
            elif page_num < 168:
                voting_type = "선거일"
            elif page_num == 168:
                voting_type = "관외사전"
            elif page_num == 169:
                voting_type = "재외투표"
            else:
                voting_type = "거소/선상"

        return PageData(
            page_num=page_num + 1,
            district=district or f"투표구_{page_num + 1}",
            voting_type=voting_type,
            candidates=candidates,
            valid_votes=valid_votes,
            invalid_votes=invalid_votes,
            total_votes=total_votes,
            raw_text=text[:500] if verbose else ""
        )

    except Exception as e:
        print(f"\nError processing page {page_num + 1}: {e}")
        return None


def analyze_pdf(pdf_path: str, start_page: int = 0, end_page: int = None,
                verbose: bool = False) -> List[PageData]:
    """PDF 전체 분석"""
    results = []

    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    if end_page is None:
        end_page = total_pages

    print(f"📄 PDF 분석: {pdf_path}")
    print(f"📝 총 {total_pages} 페이지 중 {start_page + 1}~{end_page} 페이지 분석")
    print("-" * 60)

    for i in range(start_page, min(end_page, total_pages)):
        progress = (i - start_page + 1) * 100 // (end_page - start_page)
        print(f"\r⏳ 처리 중: {i + 1}/{end_page} ({progress}%)", end="", flush=True)

        page_data = process_page(doc, i, verbose)
        if page_data:
            results.append(page_data)

    print(f"\n✅ 완료: {len(results)} 페이지 처리됨")
    doc.close()

    return results


def create_dataframe(results: List[PageData], selected_candidates: List[str] = None) -> pd.DataFrame:
    """결과를 DataFrame으로 변환"""
    if selected_candidates is None:
        selected_candidates = TARGET_CANDIDATES

    rows = []
    for data in results:
        row = {
            '페이지': data.page_num,
            '투표구': data.district,
            '유형': data.voting_type,
            '유효투표': data.valid_votes,
            '무효투표': data.invalid_votes,
            '총계': data.total_votes,
        }

        for candidate in data.candidates:
            if candidate.name in selected_candidates:
                row[f'{candidate.name}_분류'] = candidate.classified
                row[f'{candidate.name}_재확인'] = candidate.reconfirm
                row[f'{candidate.name}_계'] = candidate.total

        rows.append(row)

    return pd.DataFrame(rows)


def print_summary(df: pd.DataFrame, selected_candidates: List[str] = None):
    """요약 출력"""
    if selected_candidates is None:
        selected_candidates = TARGET_CANDIDATES

    print("\n" + "=" * 70)
    print("📊 21대 대선 개표 감사 결과 요약 (심사·집계부)")
    print("=" * 70)

    print(f"\n📌 총 분석 페이지: {len(df)}")

    total_valid = df['유효투표'].sum()
    total_invalid = df['무효투표'].sum()
    total_all = df['총계'].sum()

    print(f"📌 총 유효투표: {total_valid:,}")
    print(f"📌 총 무효투표: {total_invalid:,}")
    print(f"📌 총 투표수: {total_all:,}")

    print("\n" + "-" * 70)
    print("🗳️  후보자별 득표 현황")
    print("-" * 70)
    print(f"{'후보자':<12} {'분류된 투표지':>18} {'재확인대상':>15} {'총계':>15} {'재확인율':>10}")
    print("-" * 70)

    for candidate in selected_candidates:
        classified_col = f'{candidate}_분류'
        reconfirm_col = f'{candidate}_재확인'
        total_col = f'{candidate}_계'

        if classified_col in df.columns:
            classified = df[classified_col].sum()
            reconfirm = df[reconfirm_col].sum()
            total = df[total_col].sum()
            rate = (reconfirm / total * 100) if total > 0 else 0

            print(f"{candidate:<12} {classified:>18,} {reconfirm:>15,} {total:>15,} {rate:>9.2f}%")

    print("-" * 70)

    # 유형별 요약
    print("\n📈 투표 유형별 현황")
    print("-" * 70)
    type_summary = df.groupby('유형').agg({
        '유효투표': 'sum',
        '무효투표': 'sum',
        '총계': 'sum'
    }).reset_index()
    for _, row in type_summary.iterrows():
        print(f"  {row['유형']:<15}: 유효 {row['유효투표']:>10,}  무효 {row['무효투표']:>8,}  총계 {row['총계']:>10,}")


def export_csv(df: pd.DataFrame, output_path: str):
    """CSV로 내보내기"""
    df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"\n💾 CSV 저장: {output_path}")


def export_excel(df: pd.DataFrame, output_path: str):
    """Excel로 내보내기"""
    try:
        df.to_excel(output_path, index=False, engine='openpyxl')
        print(f"💾 Excel 저장: {output_path}")
    except Exception as e:
        print(f"⚠️  Excel 저장 실패: {e}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='21대 대선 개표상황표 분석 (로컬 OCR)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예제:
  # 전체 PDF 분석
  python analyze_election.py jeju.pdf

  # 처음 10페이지만 분석
  python analyze_election.py jeju.pdf --sample 10

  # 특정 페이지 범위
  python analyze_election.py jeju.pdf --start 0 --end 50

  # 특정 후보자만 분석
  python analyze_election.py jeju.pdf -c 이재명 김문수

  # 상세 출력
  python analyze_election.py jeju.pdf --sample 3 -v
        """
    )
    parser.add_argument('pdf_path', nargs='?', default='/home/user/K21elec/jeju.pdf',
                        help='분석할 PDF 파일 경로')
    parser.add_argument('--start', type=int, default=0,
                        help='시작 페이지 (0부터, 기본: 0)')
    parser.add_argument('--end', type=int, default=None,
                        help='끝 페이지 (기본: 전체)')
    parser.add_argument('--output', '-o', default='election_analysis.csv',
                        help='출력 파일명 (기본: election_analysis.csv)')
    parser.add_argument('--candidates', '-c', nargs='+', default=None,
                        help='분석할 후보자 (기본: 전체 5명)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='상세 출력 (OCR 텍스트 표시)')
    parser.add_argument('--sample', '-s', type=int, default=None,
                        help='샘플 페이지 수 (테스트용)')

    args = parser.parse_args()

    # 샘플 모드
    if args.sample:
        args.end = args.start + args.sample

    # 후보자 필터
    selected = args.candidates if args.candidates else TARGET_CANDIDATES

    print("=" * 70)
    print("🗳️  21대 대선 개표상황표 분석 시스템")
    print("    (로컬 Tesseract OCR 사용 - API 불필요)")
    print("=" * 70)
    print(f"📋 대상 후보자: {', '.join(selected)}")
    print()

    # PDF 분석
    results = analyze_pdf(args.pdf_path, args.start, args.end, args.verbose)

    if not results:
        print("❌ 분석된 데이터가 없습니다.")
        return

    # DataFrame 생성
    df = create_dataframe(results, selected)

    # 요약 출력
    print_summary(df, selected)

    # 저장
    export_csv(df, args.output)

    # Excel도 저장
    excel_path = args.output.replace('.csv', '.xlsx')
    export_excel(df, excel_path)

    print("\n" + "=" * 70)
    print("🎉 분석 완료!")
    print("=" * 70)


if __name__ == '__main__':
    main()
