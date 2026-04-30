# Tapo Viewer

Windows 11 üzerinde TP-Link Tapo (ve ONVIF/RTSP destekli diğer) IP kameralarınızı izlemek için tasarlanmış, modern Apple tarzı arayüze sahip bir Python masaüstü uygulamasıdır.

Sadece izleme odaklıdır. Hareket veya kişi algılama gibi özellikler içermez.

## Özellikler

- Modern, koyu temalı, Apple tarzı arayüz (PyQt6 + özel QSS)
- Çoklu kamera için **grid (ızgara) görünümü**, sütun sayısı **Ayarlar** üzerinden 1–8 arası seçilebilir
- Bir kameraya **tıklayarak seçim**, **çift tıklayınca tam ekran**; tekrar çift tık / `Esc` / "Tüm Izgara" ile geri dönüş
- **Sol menüden veya kamera kutusuna tıklayarak** kamera seçimi (seçili kamera çerçeveyle vurgulanır)
- **Sürükle-bırak** ile sol menüde kameraları yeniden sıralama (yerleşim de güncellenir)
- **Sağ tık menüsü** ile kamera düzenleme/kaldırma — sol menüde sadece "Kamera Ekle" düğmesi vardır
- **Ses açma/kapama** her kamera için ayrı düğme; varsayılan olarak tüm sesler kapalıdır
- **Kamera Hareket** paneli yalnızca bir kamera seçildiğinde görünür; kamera adı net şekilde yazılır ve panel sol menüde ortalıdır
- **Mouse tekerleği ile zoom**, sürükleyerek pan; sağ tık zoom'u sıfırlar
- Kalıcı yapılandırma (`%APPDATA%/TapoViewer/config.json`)
- **Ayarlar penceresi**: hedef FPS, sütun sayısı, yeniden bağlanma süresi, donanım hızlandırma seçimi, durum rozetini gösterme — değişiklikler **canlı** uygulanır, FPS değişimi artık uygulamayı kilitlemez
- Otomatik **yeniden bağlanma** ve canlı **bağlantı durumu rozeti** (connecting / online / offline)
- Sağ alt durum çubuğunda **CPU / GPU / Ağ kullanımı** göstergesi
- Sol menü gizlendiğinde **kalın `‹` / `›` okları** ile genişletme/daraltma düğmesi net görünür
- TCP üzerinden RTSP (varsayılan), düşük gecikme için ayarlanmış FFmpeg seçenekleri

## Kurulum

> Python 3.10+ gerekir. Windows 11'de FFmpeg, `opencv-python` ile birlikte gelir; ayrıca yüklemek gerekmez. GPU yüzdesi `nvidia-smi` varsa otomatik gelir; aksi halde "n/a" gösterilir.

### Önerilen: tek tıkla başlatma (izole `.venv` ile)

Sistemdeki diğer Python paketleriyle çakışmaması için uygulama kendi sanal ortamında (`.venv`) çalışır. İlk çalıştırmada otomatik olarak `.venv` oluşturulur ve bağımlılıklar yalnızca o dizine kurulur — sistem Python'ınız etkilenmez.

**Komut isteminden:**

```cmd
run.bat
```

**PowerShell'den:**

```powershell
.\run.ps1
```

> Not: PowerShell scriptlerinin çalışmasına izin verilmiyorsa bir kerelik şu komutu çalıştırın:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

`run.bat` / `run.ps1` her başlatmada `requirements.txt` değişip değişmediğini kontrol eder; sadece değişmişse `pip install` çalıştırır, aksi halde doğrudan uygulamayı başlatır.

### Manuel kurulum

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

`.venv` klasörü `.gitignore` ile dışlanmıştır ve repodan ayrı kalır.

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
| `Ctrl+B`    | Sol menüyü daralt/genişlet  |

## Mouse

| Hareket               | İşlev                        |
|-----------------------|------------------------------|
| Sol tık (kamera)      | Kamerayı seç                 |
| Çift tık (kamera)     | Tam ekran / geri al          |
| Sağ tık (sol menü)    | Düzenle / Kaldır menüsü      |
| Tekerlek              | Zoom (cursor merkezli)       |
| Sürükle (zoom > 1.0)  | Pan                          |
| Sağ tık (kamera)      | Zoom'u sıfırla               |
| Sürükle-bırak (liste) | Kameraları yeniden sırala    |

## Mimari

```
main.py                     # giriş noktası
app/main_window.py          # ana pencere + sidebar + sağ tık menüsü
app/camera_grid.py          # ızgara + tam ekran modu + seçim
app/camera_tile.py          # tek kamera widget'ı (zoom/pan/ses)
app/camera_list.py          # sürüklenebilir kamera listesi + ses düğmesi
app/stream_worker.py        # arka plan RTSP okuyucu (canlı FPS güncellemeli)
app/dialogs.py              # kamera + ayarlar diyalogları
app/ptz_panel.py            # ONVIF hareket paneli (seçili kamera için)
app/onvif_ptz.py            # ONVIF arka plan thread'i
app/resource_monitor.py     # CPU / GPU / Ağ göstergesi
app/config.py               # yapılandırma kalıcılığı
app/styles.py               # Apple tarzı QSS
```

Her kamera kendi `QThread`'inde çalışır. OpenCV `VideoCapture` (FFmpeg backend) frame'leri yakalar, `pyqtSignal` ile UI thread'ine iletir, `QPainter` ile çizilir. Ses gerektiğinde paralel bir `QMediaPlayer` ile çalınır; varsayılan kapalıdır.
