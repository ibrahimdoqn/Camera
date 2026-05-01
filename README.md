# Tapo Viewer

Windows 11 üzerinde TP-Link Tapo (ve ONVIF/RTSP destekli diğer) IP kameralarınızı izlemek için tasarlanmış, modern Apple tarzı arayüze sahip bir Python masaüstü uygulamasıdır.

Sadece izleme odaklıdır. Hareket veya kişi algılama gibi özellikler içermez.

## Özellikler

- Modern, koyu temalı, Apple tarzı arayüz (PyQt6 + özel QSS)
- **Animasyonlu açılış (splash) ekranı**: Windows 11 tarzı **dönen ilerleme halkası** (progress ring) ile birlikte aşamayı yazan bir alt başlık gösterilir (örn. *"Kameralara bağlanılıyor"*, *"3 / 4 kamera hazır"*); kart gölgesi artık manuel çizilir, böylece Windows'ta bazı sürücülerde görülen `UpdateLayeredWindowIndirect failed` uyarısı oluşmaz
- Çoklu kamera için **grid (ızgara) görünümü**, sütun sayısı **Ayarlar** üzerinden 1–8 arası seçilebilir
- Bir kameraya **tıklayarak seçim**, **çift tıklayınca tam ekran**; tekrar çift tık / `Esc` / "Tüm Izgara" ile geri dönüş
- **Sol menüden veya kamera kutusuna tıklayarak** kamera seçimi (seçili kamera çerçeveyle vurgulanır). Seçili kamera tile'ında ad ve durum rozeti **büyütülerek beyaz halka ile çevrelenir**, böylece mavi seçim kenarlığının içinde de net okunur
- **Sürükle-bırak** ile sol menüde kameraları yeniden sıralama: tutulan kart **yuvarlak köşeli, gölgeli bir önizleme** olarak imleçle taşınır (önceki sürümlerdeki keskin kutu görüntüsü kalktı); art arda yapılan sıralamalarda artık kilitlenme oluşmaz (`rowsMoved` sinyali sıralama tamamlandıktan sonra yeniden yayınlanır ve liste güvenli biçimde yeniden oluşturulur)
- **Modern kamera kartı**: kart üzerinde durum noktası, ad, alt başlık (ör. *IP kamera*), ses düğmesi ve **3 nokta (⋮) menü düğmesi**. IP adresi listede artık görünmez; istenirse "Bilgi" menüsünden açılır
- **3 nokta / sağ tık menüsü**: Bilgi (cihaz özetini açar), Düzenle, **Yerel ağda yeniden bul** (MAC ile), Kaldır
- **Ses açma/kapama** her kamera için ayrı düğme; varsayılan olarak tüm sesler kapalıdır. Ses, RTSP'yi gerçekten çözebilen **libVLC** üzerinden çalınır (yedek olarak Qt `QMediaPlayer`)
- **Kamera Hareket (PTZ)** paneli yalnızca bir kamera seçildiğinde görünür; kamera adı net şekilde yazılır ve panel sol menüde ortalıdır. PTZ ok düğmeleri ve durdur düğmesi artık **özel çizilmiş** simgelerle (font'tan bağımsız) **piksel hassasiyetle** ortalıdır
- ONVIF PTZ keşfi **uygulama açılışında** her kamera için arka planda yapılır — kameraya tıkladığınızda hareket panelinde **bekleme yoktur**, kontroller anında hazırdır
- **Mouse tekerleği ile zoom artık imleç merkezlidir**: tekerleği çevirdiğiniz noktanın üzerine yakınlaşır; sürükleyerek pan; sağ tık zoom'u sıfırlar
- **Daraltılmış sol menüde aç/kapa düğmesi**: chevron simgesi de **özel çizilir**, yatayda ve dikeyde tam ortalıdır (Unicode karakterlerin font'a göre kayma sorunu giderildi)
- Kalıcı yapılandırma (`%APPDATA%/TapoViewer/config.json`); kamera başına **MAC adresi** ve **son görüldüğü IP** otomatik olarak saklanır
- **MAC adresine göre IP yeniden keşif**: bir kameranın IP'si değiştiğinde (DHCP rotasyonu) yerel /24 ağı taranıp aynı MAC adresi tekrar bulunur, RTSP portu açık ise kamera otomatik yeni IP'ye taşınır. Manuel tetikleme için 3-nokta menüsünde **"Yerel ağda yeniden bul"** seçeneği vardır. Bu özellik Ayarlar üzerinden kapatılabilir
- **Dosya tabanlı log kayıtları**: Ayarlar'dan açılınca olaylar `%APPDATA%/TapoViewer/logs/tapoviewer.log` altına dönen (rotating) bir dosyaya yazılır. Log seviyesi DEBUG / INFO / WARNING / ERROR olarak seçilebilir; varsayılan kapalıdır
- **Ayarlar penceresi**: hedef FPS, sütun sayısı, yeniden bağlanma süresi, donanım hızlandırma seçimi, durum rozetini gösterme, **log kayıtları**, **log seviyesi**, **MAC tabanlı IP yeniden keşif** — değişiklikler **canlı** uygulanır, FPS değişimi artık uygulamayı kilitlemez
- Otomatik **yeniden bağlanma** ve canlı **bağlantı durumu rozeti** (connecting / online / offline)
- Sağ alt durum çubuğunda **CPU / GPU / Ağ kullanımı** göstergesi
- TCP üzerinden RTSP (varsayılan), düşük gecikme için ayarlanmış FFmpeg seçenekleri

## Kurulum

> Python 3.10+ gerekir. Windows 11'de FFmpeg, `opencv-python` ile birlikte gelir; ayrıca yüklemek gerekmez. GPU yüzdesi `nvidia-smi` varsa otomatik gelir; aksi halde "n/a" gösterilir.
>
> **Ses için VLC**: RTSP ses akışını çalmak için sistemde [VLC](https://www.videolan.org/vlc/) kurulu olmalıdır (32/64-bit Python ile aynı mimaride). `python-vlc` paketi `requirements.txt` ile kurulur; ancak `libvlc.dll` sistemde yoksa ses çalmaz (uygulama yine de hatasız çalışmaya devam eder).

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

| Hareket                       | İşlev                                       |
|-------------------------------|---------------------------------------------|
| Sol tık (kamera)              | Kamerayı seç                                |
| Çift tık (kamera)             | Tam ekran / geri al                         |
| ⋮ düğmesi (sol menü)          | Bilgi / Düzenle / Yeniden bul / Kaldır      |
| Sağ tık (sol menü)            | Bilgi / Düzenle / Yeniden bul / Kaldır      |
| Tekerlek                      | Zoom (cursor merkezli)                      |
| Sürükle (zoom > 1.0)          | Pan                                         |
| Sağ tık (kamera)              | Zoom'u sıfırla                              |
| Sürükle-bırak (liste)         | Kameraları yeniden sırala                   |

## Mimari

```
main.py                     # giriş noktası (splash → ana pencere)
app/splash.py               # Win11 ilerleme halkası animasyonu (loading)
app/main_window.py          # ana pencere + sidebar + 3-nokta menüsü
app/camera_grid.py          # ızgara + tam ekran modu + seçim
app/camera_tile.py          # tek kamera widget'ı (zoom/pan/ses)
app/camera_list.py          # sürüklenebilir kamera listesi + ses + ⋮ menü
app/stream_worker.py        # arka plan RTSP okuyucu (canlı FPS güncellemeli)
app/dialogs.py              # kamera + ayarlar + cihaz bilgisi diyalogları
app/ptz_panel.py            # ONVIF hareket paneli (özel çizilmiş ok ikonları)
app/onvif_ptz.py            # ONVIF arka plan thread'i + PtzManager (ön-yükleme)
app/resource_monitor.py     # CPU / GPU / Ağ göstergesi
app/network_scan.py         # MAC tabanlı yerel ağ IP yeniden keşif
app/logger.py               # döner dosya tabanlı tanılama logu
app/config.py               # yapılandırma kalıcılığı (kamera + MAC + ayarlar)
app/styles.py               # Apple tarzı QSS
```

Her kamera kendi `QThread`'inde çalışır. OpenCV `VideoCapture` (FFmpeg backend) frame'leri yakalar, `pyqtSignal` ile UI thread'ine iletir, `QPainter` ile çizilir. Ses gerektiğinde paralel bir **libVLC** oynatıcısıyla çalınır (RTSP'yi destekler); libVLC bulunmazsa Qt `QMediaPlayer` yedek olarak denenir. Varsayılan olarak tüm sesler kapalıdır.

ONVIF (PTZ) bağlantıları açılış sırasında `PtzManager` tarafından her kamera için arka planda kurulur; yetenek/preset bilgileri önbelleğe alınır. Hareket paneli açıldığında bu önbellek kullanıldığı için kamera değiştirirken bekleme yaşanmaz.

MAC tabanlı IP yeniden keşif (`network_scan.py`) için ufak bir QThread havuzu kullanılır: bir kamera ilk kez bağlandığında işletim sisteminin ARP tablosundan kendi MAC'i öğrenilir; bağlantı kopup yeniden bağlanma zaman aşımına uğrarsa yerel /24 ağ ICMP ile uyandırılır ve aynı MAC bulunmaya çalışılır. Bulunan yeni IP RTSP portunda erişilebiliyorsa kamera kaydı otomatik güncellenir, kullanıcıya durum çubuğunda bilgi verilir.

Tanılama log'ları `logger.configure_logging` üzerinden ayarlardan açılıp kapatılabilir; etkinse `%APPDATA%/TapoViewer/logs/tapoviewer.log` altına 512 KB sınırlı 4 yedekli **rotating file handler** ile yazılır.
