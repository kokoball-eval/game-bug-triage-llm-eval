"""현역 트리아지 파이프라인 — 출력 형식 v2, 평가셋 aether_raid_v13·v14.

    contract   출력 형식 정의·파싱·형식 채점 (R1~R7)
    prompt     시스템 프롬프트와 입력·재요청·폐기 확인 프롬프트 조립
    methods    (v1.4) 방법 M1 판정 예시, M2 Critical 체크리스트
    run        평가셋 실행 (형식 재요청, Critical 체크리스트, 폐기 확인, 후처리 안전장치 적용)
    guardrail  후처리 안전장치 — [처리] 규칙 보정
    score      정답 대조 채점
    gate       회귀 게이트 판정 (v1.3 평가셋)
    screen     (v1.4) 후보 모델 사전 점검
    selection  (v1.4) 모델 교체 판정
    compare    (v1.4) 방법·모델 비교 판정 (사전 등록 기준)
"""
