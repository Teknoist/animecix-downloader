# AnimeciX Downloader

AnimeciX üzerinden anime bölümlerini (veya tüm sezonları) otomatik olarak en yüksek kalitede indirebilen, `yt-dlp` benzeri bir komut satırı aracıdır.

## Özellikler

- **Otomatik Klasörleme**: İndirilen animeleri otomatik olarak `Dizi Adı / Sezon / Bölüm.mp4` yapısında klasörler.
- **Toplu İndirme**: Bir sezon linki verdiğinizde o sezondaki tüm bölümleri tespit edip sırayla indirir.
- **Tekil İndirme**: İsterseniz sadece tek bir bölümün linkini vererek indirebilirsiniz.
- **En İyi Kalite**: `yt-dlp` altyapısı sayesinde videonun erişilebilir en iyi kalitesini (1080p vb.) otomatik seçer.
- **Akıllı Fansub Seçimi**: Birden fazla çeviri grubu (SeiCode, Eternal vb.) arasından çalışan iframe'i bulana kadar dener.
- **M3U8 ve MP4 Yakalama**: Playwright ile arka planda network trafiğini dinleyerek gizli video kaynaklarını çözer.

## Kurulum

1. **Python 3.8+** yüklü olduğundan emin olun.
2. Bu depoyu klonlayın veya indirin.
3. Gerekli kütüphaneleri yükleyin:
   ```bash
   pip install -r requirements.txt
   ```
4. Playwright için tarayıcıları yükleyin:
   ```bash
   playwright install chromium
   ```

## Kullanım

Aracı terminalden aşağıdaki gibi kullanabilirsiniz:

```bash
python animecix_dl.py "https://animecix.tv/titles/7350/mushoku-tensei-jobless-reincarnation/season/3"
```

### Argümanlar:
- `url`: İndirmek istediğiniz AnimeciX sezon veya bölüm linki.

## Geliştirici

Bu proje bir yapay zeka tarafından (Antigravity) oluşturulmuştur.
