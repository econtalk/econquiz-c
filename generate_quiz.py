"""
generate_quiz.py — 3단계 퀴즈 생성
─────────────────────────────────────
1단계: 네이버 뉴스 API → 경제 뉴스 후보 수집
2단계: Gemini          → 핵심 뉴스 15개 선정 + 요약
3단계: Claude          → 15개 뉴스 기반, 난이도별 7개씩 총 35개 퀴즈 생성
                         같은 문제 세트 내 기사 중복 최소화

환경변수:
  ANTHROPIC_API_KEY   = sk-ant-...
  GEMINI_API_KEY      = AIza...
  NAVER_CLIENT_ID     = 네이버 앱 Client ID
  NAVER_CLIENT_SECRET = 네이버 앱 Client Secret
"""

import anthropic
import json
import re
import os
import random
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
today         = datetime.now(KST).strftime('%Y-%m-%d')
today_display = datetime.now(KST).strftime('%Y.%m.%d')

ALLOWED_DOMAINS = [
    'chosun.com', 'joongang.co.kr', 'donga.com', 'hani.co.kr',
    'seoul.co.kr', 'hankookilbo.com', 'segye.com',
    'mk.co.kr', 'hankyung.com', 'sedaily.com', 'newstomato.com',
    'yna.co.kr', 'yonhapinfomax.co.kr',
    'economist.com', 'ft.com', 'nytimes.com',
    'theguardian.com', 'reuters.com', 'bloomberg.com'
]

# ═══════════════════════════════════════
# 1단계: 네이버 뉴스 API
# ═══════════════════════════════════════
def fetch_news_from_naver():
    client_id     = os.environ.get('NAVER_CLIENT_ID')
    client_secret = os.environ.get('NAVER_CLIENT_SECRET')
    if not client_id or not client_secret:
        raise EnvironmentError("NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET 없음")

    print("📰 [1단계] 네이버 뉴스 API 검색 중...")

    keywords = [
        '경제 금리 환율', '주가 코스피 증시',
        '물가 수출 무역', '기업 실적 산업',
        '부동산 소비 고용', '한국은행 재정 정책',
        '반도체 배터리 수출', '원달러 채권 금융',
        '글로벌 경기', 'GDP 성장률', '미국 연준', '중국 경제'
    ]
    candidates = []

    for kw in keywords:
        query   = urllib.parse.quote(kw)
        api_url = (f"https://openapi.naver.com/v1/search/news.json"
                   f"?query={query}&display=20&sort=date")
        req = urllib.request.Request(api_url, headers={
            'X-Naver-Client-Id':     client_id,
            'X-Naver-Client-Secret': client_secret,
        })
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read().decode())

        for item in data.get('items', []):
            url    = item.get('originallink') or item.get('link', '')
            title  = re.sub(r'<[^>]+>', '', item.get('title', ''))
            desc   = re.sub(r'<[^>]+>', '', item.get('description', ''))
            source = item.get('source', '')

            # 허용 도메인 필터
            if not any(d in url for d in ALLOWED_DOMAINS):
                continue
            # 네이버 래퍼 URL 제거
            if 'n.news.naver.com' in url or 'news.naver.com' in url:
                if item.get('originallink'):
                    url = item['originallink']
                else:
                    continue
            if not url.startswith('http'):
                continue

            candidates.append({'title': title, 'desc': desc,
                                'url': url, 'source': source or '언론사'})

    # 중복 URL 제거
    seen, unique = set(), []
    for c in candidates:
        if c['url'] not in seen:
            seen.add(c['url'])
            unique.append(c)

    print(f"  ✅ 후보 {len(unique)}개 수집")
    return unique


# ═══════════════════════════════════════
# 2단계: Gemini → 핵심 뉴스 15개 선정
# ═══════════════════════════════════════
def select_news_with_gemini(candidates):
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY 없음")

    print("\n🔍 [2단계] Gemini로 핵심 뉴스 15개 선정 중...")

    cand_text = ""
    for i, c in enumerate(candidates[:60], 1):
        cand_text += (f"{i}. [{c['source']}] {c['title']}\n"
                      f"   URL: {c['url']}\n"
                      f"   요약: {c['desc']}\n\n")

    prompt = f"""
아래는 오늘({today_display}) 네이버 뉴스에서 수집한 경제 뉴스 목록이에요.
이 중에서 가장 화제성 있고 생활과 밀접한 뉴스 15개를 골라주세요.

[선정 기준]
- 일반인도 "어, 나도 들어봤는데!" 할 만한 화제성
- 금리·환율·주가·무역·기업실적·물가 등 생활 직결
- 주제 다양성 — 비슷한 뉴스 중복 선정 금지
- 구체적인 수치가 포함된 뉴스 우선

[URL 규칙] 반드시 위 목록의 URL을 그대로 복사할 것. 절대 변경·임의생성 금지.

[후보 목록]
{cand_text}

각 뉴스에 대해 3~5문장 상세 요약을 작성해줘 (수치 필수 포함).

[출력] JSON만, 다른 텍스트 없이:
{{
  "news": [
    {{
      "title": "기사 제목",
      "summary": "상세 요약 (수치 포함, 3~5문장)",
      "url": "위 목록 URL 그대로",
      "source": "언론사명"
    }}
  ]
}}
"""

    url     = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"gemini-2.5-flash-lite:generateContent?key={api_key}")
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 6000}
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as res:
        data = json.loads(res.read().decode())

    candidate = data["candidates"][0]
    print(f"  finishReason: {candidate.get('finishReason', 'unknown')}")
    if "content" not in candidate:
        raise ValueError("Gemini content 없음")

    raw = "".join(p["text"] for p in candidate["content"]["parts"] if "text" in p)
    print(f"  Gemini 응답 길이: {len(raw)}자")

    news_list = _parse_json(raw).get("news", [])[:15]

    # URL 검증 — 후보 목록에 없으면 제목 매칭으로 보정
    cand_url_map = {c['url']: c for c in candidates}
    for n in news_list:
        if n.get('url') not in cand_url_map:
            for c in candidates:
                if c['title'][:10] in n['title'] or n['title'][:10] in c['title']:
                    n['url'] = c['url']
                    break
            else:
                n['url'] = None

    print(f"  ✅ 뉴스 {len(news_list)}개 선정:")
    for i, n in enumerate(news_list, 1):
        print(f"    {i:2}. {n['title'][:40]}")
        print(f"        🔗 {n.get('url') or '링크없음'}")

    return news_list


# ═══════════════════════════════════════
# 3단계: Claude → 퀴즈 35개 생성
# ─────────────────────────────────────
# 설계 원칙:
#   · 15개 뉴스를 난이도별 3개씩 배분 (일부 중복 허용)
#   · 각 난이도 내 7문제는 서로 다른 뉴스 사용
#   · article_url은 Python에서 직접 주입 (Claude에게 맡기지 않음)
# ═══════════════════════════════════════
LEVELS = ['lv-easy', 'lv-mid', 'lv-hard', 'lv-expert', 'lv-master']

def assign_news_to_levels(news_list):
    """
    15개 뉴스를 5개 난이도에 배분.
    각 난이도마다 3개씩 배정 (15 / 5 = 3).
    난이도가 올라갈수록 더 복잡한 뉴스(지표·정책·이론 관련)를 배치.
    """
    n = len(news_list)
    seg = max(1, n // 5)
    assignment = {}
    for i, lv in enumerate(LEVELS):
        start = i * seg
        end   = start + seg if i < 4 else n
        assignment[lv] = news_list[start:end]
    return assignment

def build_quiz_prompt(news_list):
    assignment = assign_news_to_levels(news_list)

    # 난이도별 뉴스 블록 구성
    level_blocks = ""
    for lv in LEVELS:
        label = {'lv-easy':'🌱 입문','lv-mid':'🔥 초급','lv-hard':'⚡ 중급',
                 'lv-expert':'💎 고급','lv-master':'👑 최고급'}[lv]
        level_blocks += f"\n[{label}용 뉴스]\n"
        for j, n in enumerate(assignment[lv], 1):
            level_blocks += (f"  뉴스{j}. {n['title']}\n"
                             f"  내용: {n['summary']}\n\n")

    return f"""
당신은 경제 퀴즈 출제 전문가입니다.
아래 제공된 뉴스를 활용해서 난이도별 퀴즈를 각 7개씩, 총 35개 만들어주세요.

{level_blocks}

━━━━━━━━━━━━━━━━━━━━━━━━━━
★ 핵심 규칙
━━━━━━━━━━━━━━━━━━━━━━━━━━
[사실 정확성]
- 정답은 해당 난이도 뉴스에 명시된 수치/단어와 정확히 일치
- 뉴스에 없는 수치 절대 금지
- 수치 문제는 각 난이도에서 최대 3개

[기사 중복 최소화]
- 같은 난이도 7개 문제 안에서 동일 뉴스를 최대 2회까지만 사용
- 각 난이도의 뉴스{len(assignment[LEVELS[0]])}개를 골고루 활용할 것

[표현 중립성]
- 정치적 논란 유발 단정 표현에는 쿠션 단어 필수
  예: "기사에 따르면", "~로 보도됐습니다", "전문가들은 ~로 분석합니다"
- "기초체력이 약하다", "심각하다" 등 단정 평가 금지

[말투] "~이에요" "~해요" "~거든요" 골고루 혼용. "~거든요" 20% 이하

━━━━━━━━━━━━━━━━━━━━━━━━━━
★ 난이도별 출제 지침
━━━━━━━━━━━━━━━━━━━━━━━━━━

[🌱 입문 (lv-easy) — 7개]
- 기사 속 핵심 경제 용어/개념을 아는지 묻는 단답형
- 오답 1~2개는 유머러스하게 (예: "내 월급도 같이 오른다 🙏")
- context: "오늘 뉴스에 이 개념이 나왔는데, 알고 있나요? 😊"

[🔥 초급 (lv-mid) — 7개]
- 기사의 주요 사실 관계 확인
- 쉽고 명확한 보기, 유머 없이

[⚡ 중급 (lv-hard) — 7개]
- 영향·결과 예측 (수혜자/피해자, 6개월 후 변화 등)

[💎 고급 (lv-expert) — 7개]
- 경제 메커니즘, 원인 추론

[👑 최고급 (lv-master) — 7개]
- 내재된 경제 이론, 중장기 전망, 변수 간 연결고리

━━━━━━━━━━━━━━━━━━━━━━━━━━
★ 각 필드 규칙
━━━━━━━━━━━━━━━━━━━━━━━━━━
context: 2문장, 친근한 말투, 정답/오답 수치 절대 미포함
q:       30자 이내
opts:    정답=뉴스 원문 일치 / 오답=그럴듯하지만 뉴스에 없는 값
exp:     3문장 이내, <strong> 핵심 키워드 강조
expert_detail:
  - <span class="expert-label">🎓 박사의 한마디</span> 로 시작
  - <p> 3개 문단 (이론 + 역사적 사례 + takeaway)
  - 마지막: <p class="takeaway"> 핵심 한 줄 정리
  - 350~450자

[출력] JSON만, 다른 텍스트 없이:
{{
  "date": "{today}",
  "quizzes": {{
    "lv-easy":   [ 7개 퀴즈 ],
    "lv-mid":    [ 7개 퀴즈 ],
    "lv-hard":   [ 7개 퀴즈 ],
    "lv-expert": [ 7개 퀴즈 ],
    "lv-master": [ 7개 퀴즈 ]
  }}
}}

각 퀴즈 객체:
{{
  "levelClass": "lv-easy",
  "source": "{today_display} · 출처명",
  "news_idx": 0,
  "context": "2문장 배경 설명",
  "q": "질문 (30자 이내)",
  "opts": ["보기1","보기2","보기3","보기4"],
  "ans": 0,
  "exp": "한 줄 해설 HTML",
  "expert_detail": "전문가 해설 HTML"
}}

news_idx는 해당 난이도에 배정된 뉴스의 인덱스 (0부터 시작).
"""


def fetch_quiz_from_claude(news_list):
    client = anthropic.Anthropic()
    print("\n🤖 [3단계] Claude로 퀴즈 생성 중... (난이도별 7개씩 총 35개)")

    prompt = build_quiz_prompt(news_list)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20000,
        messages=[{"role": "user", "content": prompt}]
    )

    texts = [b.text for b in msg.content if hasattr(b, 'text') and b.text.strip()]
    if not texts:
        raise ValueError("Claude 텍스트 응답 없음")

    raw = max(texts, key=len)
    stop_reason = msg.stop_reason
    print(f"  Claude 응답 길이: {len(raw)}자 (stop_reason: {stop_reason})")

    # stop_reason이 max_tokens면 응답이 잘린 것 → 분할 호출
    if stop_reason == 'max_tokens':
        print("  ⚠️ 응답 잘림 감지 — 난이도별 분할 호출로 전환")
        return fetch_quiz_split(news_list, client)

    data    = _parse_json(raw)
    quizzes = data.get('quizzes', {})

    # 퀴즈 수 검증 — 부족한 난이도 있으면 분할 호출
    missing = [lv for lv in LEVELS if len(quizzes.get(lv, [])) < 7]
    if missing:
        print(f"  ⚠️ 부족한 난이도: {missing} — 분할 호출로 전환")
        return fetch_quiz_split(news_list, client)

    return _inject_urls_and_shuffle(data, news_list)


def fetch_quiz_split(news_list, client):
    """난이도를 2그룹으로 나눠서 각각 호출"""
    assignment = assign_news_to_levels(news_list)
    all_quizzes = {}

    groups = [
        ['lv-easy', 'lv-mid', 'lv-hard'],
        ['lv-expert', 'lv-master']
    ]

    for g_idx, group_levels in enumerate(groups):
        print(f"  분할 호출 {g_idx+1}/2: {group_levels}")

        # 해당 그룹 뉴스만 포함한 프롬프트
        level_blocks = ""
        for lv in group_levels:
            label = {'lv-easy':'🌱 입문','lv-mid':'🔥 초급','lv-hard':'⚡ 중급',
                     'lv-expert':'💎 고급','lv-master':'👑 최고급'}[lv]
            level_blocks += f"\n[{label}용 뉴스]\n"
            for j, n in enumerate(assignment[lv], 1):
                level_blocks += f"  뉴스{j}. {n['title']}\n  내용: {n['summary']}\n\n"

        lv_json = {lv: f"[ 7개 퀴즈 ]" for lv in group_levels}
        split_prompt = f"""
당신은 경제 퀴즈 출제 전문가입니다.
아래 뉴스로 난이도별 퀴즈를 각 7개씩 만들어주세요.

{level_blocks}

[규칙 요약]
- 정답: 뉴스 원문 수치/단어와 정확히 일치
- 수치 문제 각 난이도 최대 3개
- 같은 난이도 7문제 안에서 동일 뉴스 최대 2회
- 단정적 표현에 쿠션 단어 필수 ("기사에 따르면" 등)
- context: 2문장, 정답 수치 미포함
- exp: 3문장, <strong> 키워드 강조
- expert_detail: <span class="expert-label">🎓 박사의 한마디</span> 시작, <p> 3문단, 마지막 <p class="takeaway">

[출력] JSON만:
{{
  "quizzes": {{
    {chr(10).join(f'"{lv}": [ 7개 퀴즈 객체 ],' for lv in group_levels).rstrip(',')}
  }}
}}

각 퀴즈 객체: {{"levelClass":"lv-easy","source":"{today_display}·출처","news_idx":0,"context":"...","q":"...","opts":["...","...","...","..."],"ans":0,"exp":"...","expert_detail":"..."}}
"""
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=12000,
            messages=[{"role": "user", "content": split_prompt}]
        )
        texts = [b.text for b in msg.content if hasattr(b, 'text') and b.text.strip()]
        raw   = max(texts, key=len) if texts else ""
        print(f"    응답 길이: {len(raw)}자")

        part_data    = _parse_json(raw)
        part_quizzes = part_data.get('quizzes', {})
        for lv in group_levels:
            all_quizzes[lv] = part_quizzes.get(lv, [])

    final_data = {'date': today, 'quizzes': all_quizzes}
    return _inject_urls_and_shuffle(final_data, news_list)


def _inject_urls_and_shuffle(data, news_list):
    """URL 주입 + 정답 랜덤 셔플"""
    assignment = assign_news_to_levels(news_list)
    quizzes    = data.get('quizzes', {})

    for lv in LEVELS:
        pool    = quizzes.get(lv, [])
        lv_news = assignment[lv]
        lv_n    = max(1, len(lv_news))

        for q in pool:
            idx  = q.get('news_idx', 0)
            news = lv_news[idx % lv_n] if lv_news else {}
            q['article_title'] = news.get('title', '')
            q['article_url']   = news.get('url', '')

            opts = q.get('opts', [])
            ans  = q.get('ans', 0)
            if not (0 <= ans < len(opts)): ans = 0
            correct = opts[ans]
            others  = [o for j, o in enumerate(opts) if j != ans]
            random.shuffle(others)
            new_pos = random.randint(0, 3)
            others.insert(new_pos, correct)
            q['opts'] = others
            q['ans']  = new_pos

        print(f"  {lv}: {len(pool)}개")

    data['quizzes'] = quizzes
    return data


# ═══════════════════════════════════════
# JSON 파싱 헬퍼
# ═══════════════════════════════════════
def _parse_json(raw):
    # 1) ```json ... ``` 코드블록 제거
    raw = re.sub(r'```(?:json)?\s*', '', raw).strip()

    # 2) 가장 바깥 { } 추출
    start = raw.find('{')
    if start == -1:
        raise ValueError("JSON { 없음:\n" + raw[:300])

    depth, end = 0, -1
    for i, ch in enumerate(raw[start:], start):
        if ch == '{':   depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0: end = i + 1; break

    if end == -1:
        raise ValueError("JSON } 없음. 응답 마지막 200자:\n" + raw[-200:])

    json_str = raw[start:end]

    # 3) 직접 파싱 시도
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e1:
        print(f"  ⚠️ 1차 파싱 실패: {e1} (위치: char {e1.pos})")
        # 오류 위치 주변 출력
        pos = e1.pos
        print(f"  오류 주변: ...{json_str[max(0,pos-60):pos+60]}...")

    # 4) 개행 제거 후 재시도
    try:
        return json.loads(json_str.replace('\n', ' ').replace('\r', ''))
    except json.JSONDecodeError as e2:
        print(f"  ⚠️ 2차 파싱 실패: {e2}")

    # 5) 제어문자 제거 후 재시도
    import unicodedata
    cleaned = ''.join(
        c for c in json_str
        if not unicodedata.category(c).startswith('C') or c in ('\n', '\t')
    )
    cleaned = cleaned.replace('\n', ' ').replace('\t', ' ')
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e3:
        raise ValueError(
            f"JSON 파싱 3회 모두 실패.\n"
            f"마지막 오류: {e3}\n"
            f"JSON 앞 500자: {json_str[:500]}\n"
            f"JSON 뒤 200자: {json_str[-200:]}"
        )


# ═══════════════════════════════════════
# 저장
# ═══════════════════════════════════════
def save(data):
    with open('quiz_today.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    labels = {'lv-easy':'🌱 입문','lv-mid':'🔥 초급','lv-hard':'⚡ 중급',
              'lv-expert':'💎 고급','lv-master':'👑 최고급'}
    quizzes = data.get('quizzes', {})
    total   = sum(len(v) for v in quizzes.values()) if isinstance(quizzes, dict) else len(quizzes)
    print(f"\n✅ quiz_today.json 저장 완료 — 총 {total}개 퀴즈")
    if isinstance(quizzes, dict):
        for lv in LEVELS:
            pool = quizzes.get(lv, [])
            print(f"  {labels[lv]}: {len(pool)}개")


# ═══════════════════════════════════════
# 실행
# ═══════════════════════════════════════
if __name__ == '__main__':
    for key in ['ANTHROPIC_API_KEY','GEMINI_API_KEY',
                'NAVER_CLIENT_ID','NAVER_CLIENT_SECRET']:
        if not os.environ.get(key):
            raise EnvironmentError(f"{key} 없음")

    candidates = fetch_news_from_naver()
    news_list  = select_news_with_gemini(candidates)
    quiz_data  = fetch_quiz_from_claude(news_list)
    save(quiz_data)
    print("\n🎉 완료!")
