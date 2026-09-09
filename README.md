# 강의 녹음 음성 복원기

강의 녹음에서 필기할 때 발생한 책상/노트북 충격음 같은 저주파 울림을 줄이고, 작게 녹음된 교수님 목소리를 듣기 편하게 만드는 웹앱입니다.

## 기능

- MP3, WAV, M4A, AAC, FLAC, OGG, OPUS, WebM 등 지원
- 최대 2GB 업로드 설정
- 파일 전체를 서버 메모리에 올리지 않고 디스크에 저장하여 긴 녹음에 대응
- 약하게 / 추천 / 강하게 보정 강도 선택
- 저주파 충격음 감소
- 지속적인 배경 잡음 감소
- 음성 다이내믹 압축 및 음량 정규화
- 처리된 WAV 파일 다운로드

## 실행

FFmpeg가 필요합니다.

```bash
pip install -r requirements.txt
python app.py
```

브라우저에서 `http://localhost:5000` 접속.

## Docker

```bash
docker build -t lecture-cleaner .
docker run -p 5000:5000 lecture-cleaner
```

## 대용량 파일 배포 시 주의

앱은 애플리케이션 레벨에서 2GB까지 허용하지만, 실제 서비스에서는 배포 플랫폼의 request body 제한, reverse proxy 제한, 디스크 용량도 확인해야 합니다. 장시간 강의 녹음이라면 충분한 임시 디스크 공간을 확보하세요.

현재 처리 결과는 `work/<job_id>/lecture_cleaned.wav`에 남습니다. 운영 환경에서는 오래된 작업 파일을 자동 삭제하는 정리 작업을 추가하는 것을 권장합니다.

## 처리 방식

FFmpeg 필터 체인을 사용합니다. 보정 강도에 따라 high-pass 필터로 저주파 충격음을 줄이고, `afftdn`으로 일정한 잡음을 완화한 뒤 compressor와 `dynaudnorm`, `loudnorm`으로 말소리를 안정적으로 들을 수 있게 합니다.
