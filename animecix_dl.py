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

def get_best_video_url(p, iframe_url):
    """
    Iframe adresinden en yüksek kalitedeki doğrudan video bağlantısını çeker.
    Öncelikle doğrudan API sorgusu yapar (1080p garantisi için), 
    gerekirse Playwright ile ağ trafiğini dinler.
    """
    # 1. TauVideo API Yöntemi (En hızlı ve en yüksek kaliteyi verir)
    if "tau-video" in iframe_url:
        match = re.search(r'embed/([a-zA-Z0-9]+)\?vid=([a-zA-Z0-9]+)', iframe_url)
        if match:
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
                        console.print(f"[bold green]En yüksek kalite seçildi:[/bold green] [yellow]{best.get('label', 'Bilinmeyen')}[/yellow]")
                        return best.get("url")
            except Exception as e:
                console.print(f"[dim]TauVideo API sorgusu başarısız, ağ dinleme deneniyor: {e}[/dim]")

    # 2. Ağ Dinleme Yöntemi (Yedek Çözüm)
    video_urls = []
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    def handle_request(request):
        if ".mp4" in request.url or ".m3u8" in request.url:
            if request.url not in video_urls:
                video_urls.append(request.url)
            
    page.on("request", handle_request)
    try:
        page.goto(iframe_url, timeout=30000)
        time.sleep(3)
        # Oynatma butonlarına tıklayarak akışı tetikle
        for selector in ['button', '.play', '.vjs-big-play-button', 'video']:
            try:
                el = page.locator(selector).first
                if el.is_visible():
                    el.click(force=True)
                    break
            except Exception:
                pass
        time.sleep(5)
    except Exception as e:
        console.print(f"[yellow]Iframe yüklenirken uyarı: {e}[/yellow]")
    
    browser.close()
    return video_urls[0] if video_urls else None

def extract_metadata_and_links(page, url):
    """
    Sayfa başlığından ve URL'den dizi adını ve sezonu çeker, 
    eğer url bir sezon sayfasıysa bölüm linklerini döndürür.
    """
    # Eğer doğrudan anime ana linki verildiyse (/titles/123/name), varsayılan olarak /season/1'e git
    if '/titles/' in url and '/season/' not in url and '/episode/' not in url:
        url = url.rstrip('/') + '/season/1'

    page.goto(url)
    time.sleep(5)
    
    series_name = "Bilinmeyen_Anime"
    season_name = "Sezon_1"
    
    # 1. URL parsing
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

    # Dosya sistemi için güvenli isimler
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

def download_episode(p, ep_url, output_dir, ep_num):
    console.print(f"\n[bold cyan]--- Bölüm {ep_num} İşleniyor ---[/bold cyan]")
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(ep_url)
    time.sleep(4)
    
    # Dinamik fansub tespiti
    buttons = page.locator("button").all()
    fs_buttons = [b for b in buttons if "translate" in b.inner_text()]
    
    target_btn = None
    preferred = ["SeiCode", "Eternal", "SomeSub", "TenseiSubs", "AprilisSubs", "HolySubs", "Eiflex", "NovZon"]
    for pref in preferred:
        for b in fs_buttons:
            if pref.lower() in b.inner_text().lower():
                target_btn = b
                break
        if target_btn:
            break
            
    if not target_btn and fs_buttons:
        target_btn = fs_buttons[0]
        
    if target_btn:
        fs_name = target_btn.inner_text().replace('\n', ' ').strip()
        console.print(f"Fansub seçiliyor: [green]{fs_name}[/green]")
        try:
            target_btn.click(force=True)
            time.sleep(4)
        except Exception:
            pass
    else:
        console.print("[yellow]Özel fansub butonu bulunamadı, varsayılan kaynak deneniyor...[/yellow]")
        
    # Iframe src al
    iframe_srcs = page.evaluate("() => Array.from(document.querySelectorAll('iframe')).map(i => i.src)")
    valid_iframes = [src for src in iframe_srcs if "tau-video" in src or "embed" in src]
    
    browser.close()
    
    if not valid_iframes:
        console.print(f"[red]Bölüm {ep_num} için uygun video çerçevesi (iframe) bulunamadı.[/red]")
        return False
        
    iframe_url = valid_iframes[0]
    console.print(f"Video sunucusu bulundu: [dim]{iframe_url}[/dim]")
    
    # Videoyu en yüksek kalitede çıkar
    target_url = get_best_video_url(p, iframe_url)
    
    if target_url:
        console.print(f"[bold green]Video kaynağı yakalandı![/bold green]")
        
        out_filename = os.path.join(output_dir, f"Episode_{int(ep_num):02d}.%(ext)s")
        
        # yt-dlp komutu oluştur
        cmd = [
            "python", "-m", "yt_dlp",
            "-f", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", out_filename,
            target_url
        ]
        
        console.print(f"[magenta]İndirme başlatılıyor (yt-dlp)...[/magenta]")
        subprocess.run(cmd)
        console.print(f"[bold green]Bölüm {ep_num} indirmesi tamamlandı.[/bold green]")
        return True
    else:
        console.print(f"[red]Bölüm {ep_num} için video kaynağı çıkarılamadı.[/red]")
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
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        console.print("Sayfa analiz ediliyor...")
        series_name, season_name, links, is_season_url = extract_metadata_and_links(page, args.url)
        browser.close()
        
        if not links:
            console.print("[red]Geçerli bir bölüm linki bulunamadı. Lütfen URL'yi kontrol edin.[/red]")
            sys.exit(1)
            
        console.print(f"Tespit Edilen Dizi: [bold green]{series_name}[/bold green]")
        console.print(f"Tespit Edilen Sezon: [bold green]{season_name}[/bold green]")
        
        if is_season_url and not args.all:
            links_to_download = interactive_selection(links)
        else:
            links_to_download = links
            
        # Dizin yapısını oluştur: output / Dizi Adı / Sezon
        base_output = os.path.normpath(args.output)
        target_dir = os.path.join(base_output, series_name, season_name)
        os.makedirs(target_dir, exist_ok=True)
        console.print(f"Kayıt konumu: [bold]{target_dir}[/bold]")
        
        for ep_url in links_to_download:
            ep_num = ep_url.split('/episode/')[-1]
            success = download_episode(p, ep_url, target_dir, ep_num)
            if not success:
                console.print(f"[red]Bölüm {ep_num} indirilirken hata oluştu, atlanıyor...[/red]")

if __name__ == "__main__":
    main()
