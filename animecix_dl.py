import argparse
import sys
import os
import time
import subprocess
import urllib.parse
import urllib.request
import json
import re

# Fix Windows console encoding
sys.stdout.reconfigure(encoding='utf-8')

from rich.console import Console
from rich.prompt import Prompt
from playwright.sync_api import sync_playwright

console = Console()

def get_best_video_from_api(iframe_url):
    """
    TauVideo iframe adresinden en yüksek kalitedeki videoyu API ile çeker.
    Eğer geçerli link varsa (1080p > 720p > 480p) döner, yoksa None döner.
    """
    if "tau-video" not in iframe_url:
        return None, None
        
    match = re.search(r'embed/([a-zA-Z0-9]+)\?vid=([a-zA-Z0-9]+)', iframe_url)
    if not match:
        return None, None
        
    embed_id, vid = match.group(1), match.group(2)
    api_url = f"https://tau-video.xyz/api/video/{embed_id}?vid={vid}"
    
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            urls = data.get("urls", [])
            if urls:
                def quality_key(item):
                    lbl = item.get('label', '')
                    num = re.findall(r'\d+', lbl)
                    return int(num[0]) if num else 0
                sorted_urls = sorted(urls, key=quality_key, reverse=True)
                best = sorted_urls[0]
                return best.get("url"), best.get("label", "1080p")
    except Exception:
        pass
        
    return None, None

def get_video_fallback(p, iframe_url):
    """
    API yanıt vermezse tarayıcı ile ağ trafiğini dinleyerek videoyu yakalar.
    """
    video_urls = []
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    
    def handle_request(request):
        if ".mp4" in request.url or ".m3u8" in request.url:
            if request.url not in video_urls:
                video_urls.append(request.url)
                
    page.on("request", handle_request)
    try:
        page.goto(iframe_url, timeout=25000)
        time.sleep(3)
        for selector in ['button', '.play', '.vjs-big-play-button', 'video']:
            try:
                el = page.locator(selector).first
                if el.is_visible():
                    el.click(force=True)
                    break
            except Exception:
                pass
        time.sleep(4)
    except Exception:
        pass
        
    browser.close()
    return video_urls[0] if video_urls else None

def extract_metadata_and_links(page, url):
    """
    Sayfa başlığından ve URL'den dizi adını ve sezonu çeker, 
    eğer url bir sezon sayfasıysa bölüm linklerini döndürür.
    """
    if '/titles/' in url and '/season/' not in url and '/episode/' not in url:
        url = url.rstrip('/') + '/season/1'

    page.goto(url)
    time.sleep(5)
    
    series_name = "Bilinmeyen_Anime"
    season_name = "Sezon_1"
    
    path_parts = urllib.parse.urlparse(url).path.split('/')
    if 'titles' in path_parts:
        try:
            idx = path_parts.index('titles')
            slug = path_parts[idx + 2]
            series_name = slug.replace('-', ' ').replace(',', '').title()
        except Exception:
            pass
            
    if 'season' in path_parts:
        try:
            idx = path_parts.index('season')
            season_num = path_parts[idx + 1]
            season_name = f"Sezon_{season_num}"
        except Exception:
            pass
    elif "/episode/" in url:
        try:
            match = re.search(r'/season/(\d+)/episode/', url)
            if match:
                season_name = f"Sezon_{match.group(1)}"
        except Exception:
            pass

    safe_series = "".join([c for c in series_name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
    safe_season = "".join([c for c in season_name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
    
    links = []
    is_season_url = "/episode/" not in url
    
    if is_season_url:
        all_hrefs = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(a => a.href).filter(h => h.includes('/episode/'))")
        links = list(set(all_hrefs))
        links.sort(key=lambda x: int(x.split('/episode/')[-1]))
    else:
        links = [url]
        
    return safe_series, safe_season, links, is_season_url

def process_episode(p, page, ep_url, output_dir, ep_num):
    console.print(f"\n[bold cyan]--- Bölüm {ep_num} İşleniyor ---[/bold cyan]")
    
    # Zaten indirilmiş mi kontrol et
    expected_file = os.path.join(output_dir, f"Episode_{int(ep_num):02d}.mp4")
    if os.path.exists(expected_file) and os.path.getsize(expected_file) > 10 * 1024 * 1024:
        console.print(f"[bold yellow]Bölüm {ep_num} zaten mevcut ({expected_file}), indirme atlanıyor.[/bold yellow]")
        return True

    # Bölüm sayfasını aç
    page.goto(ep_url, timeout=30000)
    time.sleep(4)
    
    # Tüm çevirmen / fansub butonlarını tespit et
    translator_buttons = page.locator(".translator-item, button:has-text('star'), button:has-text('translate')").all()
    
    target_video_url = None
    target_quality = "Bilinmeyen"
    selected_fansub = "Varsayılan"
    
    if translator_buttons:
        console.print(f"[dim]{len(translator_buttons)} adet fansub/çevirmen seçeneği tespit edildi, çalışan kaynak aranıyor...[/dim]")
        for btn in translator_buttons:
            try:
                raw_name = btn.inner_text().replace('\n', ' ').strip()
                # Temiz isim
                fs_name = re.sub(r'(translate|play_arrow|star|\d+\.\d+)', '', raw_name).strip()
                if not fs_name:
                    fs_name = raw_name
                    
                btn.scroll_into_view_if_needed()
                btn.click(force=True)
                time.sleep(2.5)
                
                # Iframe ara
                iframe_srcs = page.evaluate("() => Array.from(document.querySelectorAll('iframe')).map(i => i.src)")
                valid = [s for s in iframe_srcs if "tau-video" in s or "embed" in s]
                if not valid:
                    continue
                    
                vid_url, quality = get_best_video_from_api(valid[0])
                if vid_url:
                    target_video_url = vid_url
                    target_quality = quality
                    selected_fansub = fs_name
                    console.print(f"Fansub seçildi: [green]{selected_fansub}[/green] | Kalite: [bold green]{target_quality}[/bold green]")
                    break
            except Exception:
                continue
                
    # Eğer doğrudan API ile bulunamadıysa mevcut iframe üzerinden dene
    if not target_video_url:
        iframe_srcs = page.evaluate("() => Array.from(document.querySelectorAll('iframe')).map(i => i.src)")
        valid = [s for s in iframe_srcs if "tau-video" in s or "embed" in s]
        if valid:
            console.print("[yellow]Ağ dinleme modu ile video yakalanıyor...[/yellow]")
            target_video_url = get_video_fallback(p, valid[0])
            target_quality = "En İyi"
            
    if not target_video_url:
        console.print(f"[red]Bölüm {ep_num} için çalışan bir video kaynağı bulunamadı, atlanıyor.[/red]")
        return False
        
    out_filename = os.path.join(output_dir, f"Episode_{int(ep_num):02d}.%(ext)s")
    
    cmd = [
        "python", "-m", "yt_dlp",
        "-f", "bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "-o", out_filename,
        target_video_url
    ]
    
    console.print(f"[magenta]İndirme başlatılıyor (yt-dlp)...[/magenta]")
    res = subprocess.run(cmd)
    if res.returncode == 0:
        console.print(f"[bold green]Bölüm {ep_num} indirmesi başarıyla tamamlandı![/bold green]")
        return True
    else:
        console.print(f"[red]Bölüm {ep_num} yt-dlp ile indirilirken hata verdi.[/red]")
        return False

def interactive_selection(links):
    console.print(f"\nToplam [bold yellow]{len(links)}[/bold yellow] bölüm tespit edildi.")
    console.print("[1] Tüm sezonu indir")
    console.print("[2] Sadece belirli bir bölümü indir (Örn: 5)")
    console.print("[3] Belirli bir bölüm aralığını indir (Örn: 3-8)")
    
    choice = Prompt.ask("Seçiminiz", choices=["1", "2", "3"], default="1")
    
    if choice == "1":
        return links
    elif choice == "2":
        ep = Prompt.ask("İndirmek istediğiniz bölüm numarası")
        try:
            ep_int = int(ep)
            filtered = [link for link in links if int(link.split('/episode/')[-1]) == ep_int]
            if not filtered:
                console.print("[red]Girdiğiniz bölüm bulunamadı.[/red]")
                sys.exit(1)
            return filtered
        except ValueError:
            console.print("[red]Lütfen geçerli bir sayı girin.[/red]")
            sys.exit(1)
    elif choice == "3":
        ep_range = Prompt.ask("Bölüm aralığı (Başlangıç-Bitiş, Örn: 3-8)")
        try:
            start, end = map(int, ep_range.split('-'))
            filtered = []
            for link in links:
                ep_num = int(link.split('/episode/')[-1])
                if start <= ep_num <= end:
                    filtered.append(link)
            if not filtered:
                console.print("[red]Bu aralıkta bölüm bulunamadı.[/red]")
                sys.exit(1)
            return filtered
        except Exception:
            console.print("[red]Hatalı format girdiniz. Örnek: 3-8[/red]")
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="AnimeciX üzerinden en yüksek kalitede anime indirme aracı.")
    parser.add_argument("url", help="AnimeciX sezon veya bölüm linki")
    parser.add_argument("--output", "-o", default="downloads", help="Ana indirme klasörü (varsayılan: downloads)")
    parser.add_argument("--all", action="store_true", help="Soruları atla ve tüm bölümleri indir (otomasyon için)")
    
    args = parser.parse_args()
    
    console.print(f"[bold blue]AnimeciX Downloader Başlatıldı[/bold blue]")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()
        
        console.print("Sayfa analiz ediliyor...")
        series_name, season_name, links, is_season_url = extract_metadata_and_links(page, args.url)
        
        if not links:
            console.print("[red]Geçerli bir bölüm linki bulunamadı. Lütfen URL'yi kontrol edin.[/red]")
            browser.close()
            sys.exit(1)
            
        console.print(f"Tespit Edilen Dizi: [bold green]{series_name}[/bold green]")
        console.print(f"Tespit Edilen Sezon: [bold green]{season_name}[/bold green]")
        
        if is_season_url and not args.all:
            links_to_download = interactive_selection(links)
        else:
            links_to_download = links
            
        base_output = os.path.normpath(args.output)
        target_dir = os.path.join(base_output, series_name, season_name)
        os.makedirs(target_dir, exist_ok=True)
        console.print(f"Kayıt konumu: [bold]{target_dir}[/bold]")
        
        for ep_url in links_to_download:
            ep_num = ep_url.split('/episode/')[-1]
            success = process_episode(p, page, ep_url, target_dir, ep_num)
            if not success:
                console.print(f"[red]Bölüm {ep_num} indirilemedi.[/red]")
            # Bölümler arası 2 saniye dinlen
            time.sleep(2)
            
        browser.close()
        console.print("\n[bold green]Tüm işlemler tamamlandı! Keyifli seyirler dileriz.[/bold green]")

if __name__ == "__main__":
    main()
