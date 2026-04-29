# Tapo Viewer

Windows 11 üzerinde TP-Link Tapo (ve ONVIF/RTSP destekli diğer) IP kameralarınızı izlemek için tasarlanmış, modern Apple tarzı arayüze sahip bir Python masaüstü uygulamasıdır.

Sadece izleme odaklıdır. Hareket veya kişi algılama gibi özellikler içermez.

## Özellikler

- Modern, koyu temalı, Apple tarzı arayüz (PyQt6 + özel QSS)
- Çoklu kamera için **grid (ızgara) görünümü**, sütun sayısı seçilebilir (1–8)
- Bir kameraya **tıklayınca tam ekran** olur, tekrar tıklayınca / Esc / "Tüm Izgara" ile geri döner
- **Mouse tekerleği ile zoom**, sürükleyerek pan; sağ tık zoom'u sıfırlar
- Kamera **ekleme, düzenleme ve silme**
- Kalıcı yapılandırma (`%APPDATA%/TapoViewer/config.json`)
- **Ayarlar penceresi**: hedef FPS, sütun sayısı, yeniden bağlanma süresi, donanım hızlandırma seçimi, durum rozetini gösterme
- Otomatik **yeniden bağlanma** ve canlı **bağlantı durumu rozeti** (connecting / online / offline)
- TCP üzerinden RTSP (varsayılan), düşük gecikme için ayarlanmış FFmpeg seçenekleri

## Kurulum

> Python 3.10+ gerekir. Windows 11'de FFmpeg, `opencv-python` ile birlikte gelir; ayrıca yüklemek gerekmez.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Tapo Kameralar İçin RTSP Hesabı

Tapo kameralarda RTSP'nin çalışabilmesi için Tapo mobil uygulamasından **Kamera Hesabı** oluşturmanız gerekir:

`Tapo App → Kamera → Ayarlar → Gelişmiş Ayarlar → Kamera Hesabı`

Burada belirlediğiniz kullanıcı adı ve şifreyi uygulamada kullanın.

URL formatı:

```
rtsp://<kullanici>:<sifre>@<ip>:554/stream1   # HD
rtsp://<kullanici>:<sifre>@<ip>:554/stream2   # SD
```

Uygulama bu URL'i girdiğiniz alanlardan otomatik üretir; isterseniz "Özel RTSP URL" seçeneğiyle elle de verebilirsiniz.

## Klavye Kısayolları

| Kısayol     | İşlev                       |
|-------------|-----------------------------|
| `Esc`       | Tam ekrandan grid'e dön     |
| `Ctrl+N`    | Yeni kamera ekle            |
| `Ctrl+,`    | Ayarları aç                 |

## Mouse

| Hareket               | İşlev                  |
|-----------------------|------------------------|
| Sol tık               | Tam ekran / geri al    |
| Çift tık              | Tam ekran / geri al    |
| Tekerlek              | Zoom (cursor merkezli) |
| Sürükle (zoom > 1.0)  | Pan                    |
| Sağ tık               | Zoom'u sıfırla         |

## Mimari

```
main.py                  # giriş noktası
app/main_window.py       # ana pencere + sidebar
app/camera_grid.py       # ızgara + tam ekran modu
app/camera_tile.py       # tek kamera widget'ı (zoom/pan)
app/stream_worker.py     # arka plan RTSP okuyucu (QThread)
app/dialogs.py           # kamera + ayarlar diyalogları
app/config.py            # yapılandırma kalıcılığı
app/styles.py            # Apple tarzı QSS
```

Her kamera kendi `QThread`'inde çalışır. OpenCV `VideoCapture` (FFmpeg backend) frame'leri yakalar, `pyqtSignal` ile UI thread'ine iletir, `QPainter` ile çizilir.
