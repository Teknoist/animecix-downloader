import argparse
import sys
import os
import time
import subprocess
import urllib.parse
from rich.console import Console
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
    Sayfa başlığından dizi adını ve sezonu çeker, 
    eğer url bir sezon sayfasıysa bölüm linklerini döndürür.
    """
    page.goto(url)
    time.sleep(5)
    
    title_text = page.title()
    # Örnek title: "Mushoku Tensei: Jobless Reincarnation (2021) 3. Sezon 1. Bölüm - AnimeciX"
    # veya "Mushoku Tensei: Jobless Reincarnation 3. Sezon - AnimeciX"
    
    series_name = "Bilinmeyen_Anime"
    season_name = "Sezon_1"
    
    parts = title_text.split(" - AnimeciX")[0].split(" Sezon ")
    if len(parts) > 1:
        series_part = parts[0].strip()
        series_name = series_part[:-3].strip() if series_part.endswith(".") else series_part
        season_name = f"Sezon {series_part[-2:].strip()}" if series_part[-2:].strip().isdigit() else "Sezon_X"
        if series_part.endswith("."):
            series_name = series_part[:-2].strip()
            season_name = f"Sezon {series_part[-1]}"
    else:
        # Fallback to URL parsing
        path_parts = urllib.parse.urlparse(url).path.split('/')
        if 'titles' in path_parts:
            try:
                idx = path_parts.index('titles')
                series_name = path_parts[idx + 2].replace('-', ' ').title()
            except:
                pass
        if 'season' in path_parts:
            try:
                idx = path_parts.index('season')
                season_name = f"Sezon {path_parts[idx + 1]}"
            except:
                pass

    # Dosya sistemi için güvenli isimler
    safe_series = "".join([c for c in series_name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
    safe_season = "".join([c for c in season_name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
    
    links = []
    if "/episode/" not in url:
        # Sezon sayfası, bölüm linklerini bul
        all_hrefs = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(a => a.href).filter(h => h.includes('/episode/'))")
        # Ensure uniqueness and sort
        links = list(set(all_hrefs))
        links.sort(key=lambda x: int(x.split('/episode/')[-1]))
    else:
        # Zaten bir bölüm linki
        links = [url]
        
    return safe_series, safe_season, links

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


def main():
    parser = argparse.ArgumentParser(description="AnimeciX üzerinden en yüksek kalitede anime indirme aracı.")
    parser.add_argument("url", help="AnimeciX sezon veya bölüm linki")
    parser.add_argument("--output", "-o", default="downloads", help="Ana indirme klasörü (varsayılan: downloads)")
    
    args = parser.parse_args()
    
    console.print(f"[bold blue]AnimeciX Downloader Başlatıldı[/bold blue]")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        console.print("Sayfa analiz ediliyor...")
        series_name, season_name, links = extract_metadata_and_links(page, args.url)
        browser.close()
        
        if not links:
            console.print("[red]Geçerli bir bölüm linki bulunamadı. Lütfen URL'yi kontrol edin.[/red]")
            sys.exit(1)
            
        console.print(f"Tespit Edilen Dizi: [bold green]{series_name}[/bold green]")
        console.print(f"Tespit Edilen Sezon: [bold green]{season_name}[/bold green]")
        console.print(f"Toplam [bold yellow]{len(links)}[/bold yellow] bölüm bulundu.")
        
        # Dizin yapısını oluştur: downloads / Dizi Adı / Sezon
        target_dir = os.path.join(args.output, series_name, season_name)
        os.makedirs(target_dir, exist_ok=True)
        console.print(f"Kayıt konumu: [bold]{target_dir}[/bold]")
        
        for ep_url in links:
            ep_num = ep_url.split('/episode/')[-1]
            success = download_episode(p, ep_url, target_dir, ep_num)
            if not success:
                console.print(f"[red]Bölüm {ep_num} indirilirken hata oluştu, atlanıyor...[/red]")

if __name__ == "__main__":
    main()
