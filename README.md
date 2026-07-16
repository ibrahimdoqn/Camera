# Tapo Viewer

Windows 11 üzerinde TP-Link Tapo (ve ONVIF/RTSP destekli diğer) IP kameralarınızı izlemek için tasarlanmış, modern Apple tarzı arayüze sahip bir Python masaüstü uygulamasıdır.

Sadece izleme odaklıdır. Hareket veya kişi algılama gibi özellikler içermez.

Video akışı **libVLC** ile çözülür — RTSP protokolünü sağlam desteklemesi ve donanım hızlandırmayı (DXVA2 / D3D11 / NVDEC / Quick Sync) sistemde varsayılan olarak native seçmesi için tercih edilmiştir.

## Özellikler

- Modern, koyu temalı, Apple tarzı arayüz (PyQt6 + özel QSS)
- **Animasyonlu açılış (splash) ekranı**: Windows 11 tarzı **dönen ilerleme halkası** (progress ring) ile birlikte aşamayı yazan bir alt başlık gösterilir (örn. *"Kameralara bağlanılıyor"*, *"3 / 4 kamera hazır"*); kart gölgesi artık manuel çizilir, böylece Windows'ta bazı sürücülerde görülen `UpdateLayeredWindowIndirect failed` uyarısı oluşmaz
- **Splash ekranı tüm kameralar yerleşene kadar açık kalır**: önceden 6 saniyelik sabit bir zaman aşımı vardı, bu yüzden ağda yavaş kalkan kameralar siyah kutu olarak göründüğünde splash erken kapanıyordu. Artık her kameranın ya **ilk karesini ürettiği** ya da **çevrim dışı/hata** olarak yerleştiği kesinleşene kadar splash açık kalır; ulaşılamayan kamera olursa ilerleme yazısında *"X / Y kamera hazır · N bağlanamadı"* olarak gösterilir. Yine de takılma olmaması için 60 saniyelik son durak (hard timeout) korunur
- Çoklu kamera için **grid (ızgara) görünümü**, sütun sayısı **Ayarlar** üzerinden 1–8 arası seçilebilir
- Bir kameraya **tıklayarak seçim**, **çift tıklayınca tam ekran**; tekrar çift tık / `Esc` / "Tüm Izgara" ile geri dönüş
- **Sol menüden veya kamera kutusuna tıklayarak** kamera seçimi (seçili kamera çerçeveyle vurgulanır). Seçili kamera tile'ında ad ve durum rozeti **büyütülerek beyaz halka ile çevrelenir**, böylece mavi seçim kenarlığının içinde de net okunur
- **Sürükle-bırak** ile sol menüde kameraları yeniden sıralama: tutulan kart **yuvarlak köşeli, gölgeli bir önizleme** olarak imleçle taşınır (önceki sürümlerdeki keskin kutu görüntüsü kalktı); art arda yapılan sıralamalarda artık kilitlenme oluşmaz (`rowsMoved` sinyali sıralama tamamlandıktan sonra yeniden yayınlanır ve liste güvenli biçimde yeniden oluşturulur)
- **Sol menüden kameraları tek tuşla göster / gizle**: her kartta yeni bir **göz simgesi** vardır. Tıklayınca kamera ızgaradan çıkar, RTSP akışı durdurulur (CPU/ağ kullanımı düşer) ve sol menüde *"Gizli"* etiketiyle, italik soluk yazı + üzeri çizili göz ikonu ile gösterilir. Tekrar tıklayınca kamera anında geri gelir ve yayın yeniden başlar; **kart yazıları da artık gri/italik görünümden çıkıp normal beyaz tipografiye döner** (önceki sürümde QSS dynamic-property polish'i sadece satıra uygulanıyor, alt etiketler `text_muted` rengine takılı kalıyordu). Gizli/görünür durum yapılandırma dosyasında saklanır, yani uygulama bir sonraki açılışta da aynı seçimi hatırlar. Splash sayacı yalnızca **görünür** kameraları sayar; durum çubuğu *"3 / 5 kamera (gizli: 2)"* biçiminde özet verir
- **Gizle/göster akışı çökmez**: önceki sürümde `Izgaradan gizle`'ye basıldığında uygulama Qt6Core.dll içinde `c0000409 / FAST_FAIL_FATAL_APP_EXIT` ile düşüyordu (`QThread: Destroyed while thread '' is still running` mesajı stdout'a basılıyordu). Üç ayrı kök neden hep birlikte eklenmiş durumda: (1) `tile.deleteLater()`'dan sonra arka plandaki RTSP iş parçacığı hâlâ `frame_ready` / `status_changed` sinyali kuyruğa atıyordu — artık `stop()` worker'a `_running=False` demeden önce sinyalleri **disconnect** ediyor, böylece worker birkaç saniye daha çalışsa bile yayınladığı sinyallerin gidecek bir alıcısı kalmıyor; (2) tile'ı yıkma işi (libVLC `stop`, RTSP capture serbest bırakma, `deleteLater` zinciri) `QPushButton` *click* dispatch'i hâlâ stack'teyken çalışıyordu — `_on_visibility_toggled` artık state'i senkron güncelleyip ızgara yeniden inşasını **`QTimer.singleShot(0, …)`** ile bir sonraki event loop turuna erteliyor (sürükle-bırak `_on_rows_moved` ile aynı pattern); (3) ESAS ÇÖKME nedeni: `self._worker = None` / `self._thread = None` ataması Python ref count'unu sıfırlıyor, PyQt'nin sip katmanı C++ `QThread` nesnesinin yok edicisini hemen çağırıyor, ama worker thread'i hâlâ `cap.read()` üzerinde bloklu olduğu için Qt `qFatal()` ile süreci öldürüyordu. Çözüm: yeni `_bury_running_thread()` worker + thread'i `sip.transferto(obj, None)` ile **Qt sahipliğine** devrediyor, böylece Python wrapper'ının GC'lenmesi C++ nesnesini etkilemiyor; mevcut `worker.finished → deleteLater` zinciri `run()` gerçekten bittikten sonra her ikisini de güvenli biçimde imha ediyor. Buna ek olarak libVLC nesneleri için `release()` çağrılmıyor (bazı sürümlerde click handler içinde tetiklendiğinde yerel crash sebebi oluyordu); sadece `stop()` çağrılıp Python referansı bırakılıyor
- **Modern kamera kartı**: kart üzerinde durum noktası, ad, alt başlık (ör. *IP kamera*), **görünürlük (göz)** düğmesi, ses düğmesi ve **3 nokta (⋮) menü düğmesi**. IP adresi listede artık görünmez; istenirse "Bilgi" menüsünden açılır
- **3 nokta / sağ tık menüsü**: Bilgi (cihaz özetini açar), Düzenle, **Yerel ağda yeniden bul** (MAC ile), Kaldır
- **Ses açma/kapama** her kamera için ayrı düğme; varsayılan olarak tüm sesler kapalıdır. Ses, RTSP'yi gerçekten çözebilen **libVLC** üzerinden çalınır (yedek olarak Qt `QMediaPlayer`)
- **Kamera Hareket (PTZ)** paneli yalnızca bir kamera seçildiğinde görünür; kamera adı net şekilde yazılır ve panel sol menüde ortalıdır. PTZ ok düğmeleri ve durdur düğmesi artık **özel çizilmiş** simgelerle (font'tan bağımsız) **piksel hassasiyetle** ortalıdır
- ONVIF PTZ keşfi **uygulama açılışında** her kamera için arka planda yapılır — kameraya tıkladığınızda hareket panelinde **bekleme yoktur**, kontroller anında hazırdır
- **Mouse tekerleği ile zoom artık imleç merkezlidir**: tekerleği çevirdiğiniz noktanın üzerine yakınlaşır; sürükleyerek pan; sağ tık zoom'u sıfırlar
- **Daraltılmış sol menüde aç/kapa düğmesi**: chevron simgesi de **özel çizilir**, yatayda ve dikeyde tam ortalıdır (Unicode karakterlerin font'a göre kayma sorunu giderildi)
- Kalıcı yapılandırma (`%APPDATA%/TapoViewer/config.json`); kamera başına **MAC adresi**, **son görüldüğü IP** ve **görünürlük (gizli/açık)** durumu otomatik olarak saklanır
- **MAC adresine göre IP yeniden keşif**: bir kameranın IP'si değiştiğinde (DHCP rotasyonu) yerel /24 ağı taranıp aynı MAC adresi tekrar bulunur, RTSP portu açık ise kamera otomatik yeni IP'ye taşınır. Manuel tetikleme için 3-nokta menüsünde **"Yerel ağda yeniden bul"** seçeneği vardır. Bu özellik Ayarlar üzerinden kapatılabilir
- **Dosya tabanlı log kayıtları**: Ayarlar'dan açılınca olaylar `%APPDATA%/TapoViewer/logs/tapoviewer.log` altına dönen (rotating) bir dosyaya yazılır. Log seviyesi DEBUG / INFO / WARNING / ERROR olarak seçilebilir; varsayılan kapalıdır
- **Ayarlar penceresi**: hedef FPS, sütun sayısı, yeniden bağlanma süresi, donanım hızlandırma seçimi, durum rozetini gösterme, **log kayıtları**, **log seviyesi**, **MAC tabanlı IP yeniden keşif** — değişiklikler **canlı** uygulanır, FPS değişimi artık uygulamayı kilitlemez. **HW hızlandırma** değişimi yalnızca o kamera için bir **yeniden bağlantı tetikler** (uygulama açık kalır), çünkü FFmpeg dekoderi `VideoCapture` oluşturulurken seçer; geçiş sırasında çökme yaşanmaması için yeni worker başlatılmadan önce eski worker'ın sinyalleri sökülür
- **libVLC dekoder + native donanım hızlandırma + güvenli geri düşüş**: uygulama tüm RTSP akışlarını **libVLC** üzerinden çözer. VLC, platformun donanım yolunu kendi seçer (Windows'ta DXVA2 / D3D11, Intel iGPU'da Quick Sync, NVIDIA'da NVDEC) ve **kareler GPU'da çözüldükten sonra** doğrudan tile'ın paint pipeline'ına akar — böylece cursor-merkezli zoom, pan, overlay rozeti ve tam ekran özelliği hepsi çalışmaya devam ederken CPU yükü belirgin biçimde düşer. Ayarlarda desteklenen tüm modlar seçilebilir: `auto` (VLC otomatik seçsin), `none` (saf CPU), `d3d11va`, `dxva2`, `cuda` (NVDEC), `qsv` (Intel Quick Sync). **Ayarlar açılır listesi yalnızca platformda çalışabilecek modları gösterir** — Windows dışında DirectX yolları gizlenir, NVIDIA GPU yoksa `cuda` listelenmez. VLCFrameWorker bir **runtime probe** çalıştırır: GPU modu seçildiyse ve ilk **6 saniye** içinde tek bir kare bile gelmezse, `none` (saf CPU) moduna **otomatik geri düşülür**, kullanıcıya log'da bilgi verilir; böylece desteklenmeyen bir mod seçilse bile kamera görüntüsü siyah kutu olarak takılı kalmaz
- Otomatik **yeniden bağlanma** ve canlı **bağlantı durumu rozeti** (connecting / online / offline). VLCFrameWorker iki katmanlı bir **gözcü (watchdog)** çalıştırır: (1) VLC'ye `--network-caching=300 --live-caching=300` verilir ve `--rtsp-tcp` ile UDP paket kaybı yaşanmadığından emin olunur; (2) son başarılı kareden bu yana 8 sn geçmişse bağlantı zorla kapatılıp yeniden açılır, ayrıca ilk kare 6 sn içinde gelmezse HW hızlandırma "bu makinede çalışmıyor" diye işaretlenir ve `none` moduna geçilir. Sonuç olarak çevrim dışı kalan her akış kendiliğinden offline rozetine düşer ve aynı yeniden bağlanma döngüsünü kullanır
- Sağ alt durum çubuğunda **CPU / GPU / Ağ kullanımı** göstergesi
- TCP üzerinden RTSP (varsayılan), düşük gecikme için ayarlanmış libVLC seçenekleri

## Kurulum

> Python 3.10+ gerekir. GPU yüzdesi `nvidia-smi` varsa otomatik gelir; aksi halde "n/a" gösterilir.
>
> **VLC ZORUNLU**: Video + ses akışı sistemdeki [VLC](https://www.videolan.org/vlc/) kurulumundaki `libvlc` üzerinden çözülür. Python ile aynı mimaride (32/64-bit) bir VLC yüklemesi gereklidir; `python-vlc` paketi `requirements.txt` ile kurulur ama libVLC sistemde yoksa uygulama video oynatamaz.

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

> **İpucu — kameraları tek tuşla gizle**: sol menüdeki kart üzerinde **göz simgesi** vardır. Bir tık ile kamerayı ızgaradan çıkarır (RTSP akışı durdurulur), tekrar tık ile geri getirir. Kart sol menüde *"Gizli"* yazısı ve üzeri çizili göz simgesi ile durmaya devam eder, böylece istediğiniz an geri açabilirsiniz.

## Mouse

| Hareket                       | İşlev                                       |
|-------------------------------|---------------------------------------------|
| Sol tık (kamera)              | Kamerayı seç                                |
| Çift tık (kamera)             | Tam ekran / geri al                         |
| 👁 düğmesi (sol menü)         | Kamerayı ızgarada göster / gizle (tek tık)  |
| 🔊 düğmesi (sol menü)         | Sesi aç / kapat                             |
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
app/vlc_view.py             # libVLC video callbacks worker (RTSP + HW decode)
app/stream_worker.py        # eski shim: vlc_view'daki isimleri yeniden ihraç eder
app/dialogs.py              # kamera + ayarlar + cihaz bilgisi diyalogları
app/ptz_panel.py            # ONVIF hareket paneli (özel çizilmiş ok ikonları)
app/onvif_ptz.py            # ONVIF arka plan thread'i + PtzManager (ön-yükleme)
app/resource_monitor.py     # CPU / GPU / Ağ göstergesi
app/network_scan.py         # MAC tabanlı yerel ağ IP yeniden keşif
app/logger.py               # döner dosya tabanlı tanılama logu
app/config.py               # yapılandırma kalıcılığı (kamera + MAC + ayarlar)
app/styles.py               # Apple tarzı QSS
```

Her **görünür** kamera kendi `QThread`'inde çalışır. Sol menüdeki göz simgesiyle gizlenen kameralar için `CameraTile` ve `VLCFrameWorker` hiç oluşturulmaz, böylece RTSP/dekoder yükü tamamen ortadan kalkar; kullanıcı tekrar görünür yaptığında thread baştan ayağa kalkar. Video çözümlemesi tamamen **libVLC** üzerinden yürür: her worker kendi `vlc.Instance`'ını `--avcodec-hw=<mod>` ile başlatır; libVLC RTSP bağlantısını `--rtsp-tcp` üzerinden kurar, kareyi platformun donanım yolunda (DXVA2/D3D11/NVDEC/QSV) çözer ve `video_set_format_callbacks` + `video_set_callbacks` çifti üzerinden **BGRA** olarak worker'ın önceden ayırdığı ctypes buffer'ına yazar. Worker frame'i `numpy` dizisine kopyalayıp `pyqtSignal` ile UI thread'ine iletir, `CameraTile._on_frame` de bunu `QImage.Format_ARGB32` olarak sarıp `QPainter` üzerinden çizer — böylece cursor merkezli zoom, sürükleyerek pan, sağ tık zoom sıfırlama ve overlay rozeti aynen çalışır. Ses aynı libVLC üzerinden ayrı bir player ile çalınır (RTSP'yi destekler); libVLC bulunmazsa Qt `QMediaPlayer` yedek olarak denenir. Varsayılan olarak tüm sesler kapalıdır. Ses durdurulduğunda libVLC nesneleri sadece `stop()` çağrısıyla kapatılıp Python referansları düşürülür — GC daha sonra `release()`'i sessiz bir anda tamamlar (click handler stack'inde tetiklenen `release()` bazı libvlc sürümlerinde çöküyordu).

`VLCFrameWorker` iki katmanlı bir **gözcü** mantığı çalıştırır. VLC oynatmaya başladığında her `unlock_cb`'de son kare zaman damgası yenilenir; **8 saniye** boyunca taze kare gelmezse VLC durdurulur, dış döngü `offline` rozetini yayar ve `reconnect_delay` sonrası yeniden bağlanır. Ayrıca `auto / cuda / dxva2 / d3d11va / qsv` gibi GPU modu seçilmişse ve **ilk** kare 6 saniye içinde gelmezse, worker bu modu "bu makinede çalışmıyor" diye işaretler ve sonraki bağlantı denemesinde sessizce `none` moduna geçer — kullanıcı siyah ekran görmez, log'a `HW hızlandırma '<mod>' çalışmıyor — CPU dekodlamaya geçiliyor` satırı düşer. Kullanıcı Ayarlar'dan farklı bir mod seçtiğinde bayrak sıfırlanır, yeni mod tekrar denenir.

Sinyal güvenliği: `CameraTile.stop()` worker'ı durdurmadan önce `frame_ready` / `status_changed` / `error` sinyallerini Python tarafında *disconnect* eder. Worker arka planda hâlâ `player.stop()` üzerinde bloklanmış olabilir; bu sırada kuyruğa girmiş bir sinyal silinmiş bir tile widget'ına ulaşırsa süreç çöker. Disconnect sayesinde worker birkaç saniye daha çalışsa bile yayınladığı sinyallerin gidecek bir alıcısı kalmaz, böylece *Izgaradan gizle* ve *Donanım hızlandırma değiştir* akışları çökme yaşamaz.

Açılış splash'ı, her görünür kamera için `CameraTile.first_frame` (başarı yolu) veya `tile_status_changed("offline"/"error")` (ulaşılamayan kamera yolu) sinyallerini bekler. İki sinyal de yerleşene kadar splash kapanmaz; en geç 60 saniye sonra son durak (hard timeout) devreye girer.

ONVIF (PTZ) bağlantıları açılış sırasında `PtzManager` tarafından her kamera için arka planda kurulur; yetenek/preset bilgileri önbelleğe alınır. Hareket paneli açıldığında bu önbellek kullanıldığı için kamera değiştirirken bekleme yaşanmaz.

MAC tabanlı IP yeniden keşif (`network_scan.py`) için ufak bir QThread havuzu kullanılır: bir kamera ilk kez bağlandığında işletim sisteminin ARP tablosundan kendi MAC'i öğrenilir; bağlantı kopup yeniden bağlanma zaman aşımına uğrarsa yerel /24 ağ ICMP ile uyandırılır ve aynı MAC bulunmaya çalışılır. Bulunan yeni IP RTSP portunda erişilebiliyorsa kamera kaydı otomatik güncellenir, kullanıcıya durum çubuğunda bilgi verilir.

Tanılama log'ları `logger.configure_logging` üzerinden ayarlardan açılıp kapatılabilir; etkinse `%APPDATA%/TapoViewer/logs/tapoviewer.log` altına 512 KB sınırlı 4 yedekli **rotating file handler** ile yazılır.
