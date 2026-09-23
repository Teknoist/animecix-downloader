import argparse
import sys
import os
import time
import subprocess
import urllib.parse
import re

# Fix Windows console encoding
sys.stdout.reconfigure(encoding='utf-8')

from rich.console import Console
from rich.prompt import Prompt, Confirm
from playwright.sync_api import sync_playwright

console = Console()

def get_mp4_from_iframe(p, iframe_url):
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
        time.sleep(6) # Wait for network requests to settle
    except Exception as e:
        console.print(f"[yellow]Iframe yüklenirken uyarı: {e}[/yellow]")
    
    browser.close()
    return video_urls

def extract_metadata_and_links(page, url):
    """
    Sayfa başlığından ve URL'den dizi adını ve sezonu kesin olarak çeker, 
    eğer url bir sezon sayfasıysa bölüm linklerini döndürür.
    """
    page.goto(url)
    time.sleep(5)
    
    series_name = "Bilinmeyen_Anime"
    season_name = "Sezon_1"
    
    # 1. URL parsing (Most reliable for AnimeciX)
    path_parts = urllib.parse.urlparse(url).path.split('/')
    if 'titles' in path_parts:
        try:
            idx = path_parts.index('titles')
            # Extract series slug and prettify
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
        # Try to extract season from episode URL
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
        # Sezon sayfası, bölüm linklerini bul
        all_hrefs = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(a => a.href).filter(h => h.includes('/episode/'))")
        links = list(set(all_hrefs))
        links.sort(key=lambda x: int(x.split('/episode/')[-1]))
    else:
        # Zaten bir bölüm linki
        links = [url]
        
    return safe_series, safe_season, links, is_season_url

def download_episode(p, ep_url, output_dir, ep_num):
    console.print(f"\n[bold cyan]--- Bölüm {ep_num} İşleniyor ---[/bold cyan]")
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(ep_url)
    time.sleep(4)
    
    # Try multiple fansub options
    fansubs = ["SeiCode", "Eternal", "TenseiSubs", "Eiflex", "SomeSub", "NovZon", "MDSubs"]
    clicked = False
    
    for fs in fansubs:
        btn = page.locator(f"text='{fs}'").first
        if btn.is_visible():
            console.print(f"Fansub seçiliyor: [green]{fs}[/green]")
            try:
                btn.click(force=True)
                time.sleep(4)
                clicked = True
                break
            except:
                pass
                
    if not clicked:
        console.print("[yellow]Özel fansub butonu bulunamadı, varsayılan kaynak deneniyor...[/yellow]")
        
    # Iframe src al
    iframe_srcs = page.evaluate("() => Array.from(document.querySelectorAll('iframe')).map(i => i.src)")
    valid_iframes = [src for src in iframe_srcs if "tau-video" in src or "embed" in src]
    
    browser.close()
    
    if not valid_iframes:
        console.print(f"[red]Bölüm {ep_num} için uygun iframe bulunamadı.[/red]")
        return False
        
    iframe_url = valid_iframes[0]
    console.print(f"Iframe bulundu: [dim]{iframe_url}[/dim]")
    
    # Videoyu Iframe'den çıkar
    mp4_urls = get_mp4_from_iframe(p, iframe_url)
    
    if mp4_urls:
        target_url = mp4_urls[0]
        console.print(f"[bold green]Video kaynağı yakalandı![/bold green] [dim]{target_url}[/dim]")
        
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
            
        # Dizin yapısını oluştur: downloads / Dizi Adı / Sezon
        target_dir = os.path.join(args.output, series_name, season_name)
        os.makedirs(target_dir, exist_ok=True)
        console.print(f"Kayıt konumu: [bold]{target_dir}[/bold]")
        
        for ep_url in links_to_download:
            ep_num = ep_url.split('/episode/')[-1]
            success = download_episode(p, ep_url, target_dir, ep_num)
            if not success:
                console.print(f"[red]Bölüm {ep_num} indirilirken hata oluştu, atlanıyor...[/red]")

if __name__ == "__main__":
    main()
