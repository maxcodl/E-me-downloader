import argparse
import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import os
import tldextract
from tqdm import tqdm
import re
from concurrent.futures import ThreadPoolExecutor

session = requests.Session()

ALLOWED_HOSTS = ["www.erome.com", "nl.erome.com", "erome.fan"]

def collect_links(album_url):
    parsed_url = urlparse(album_url)
    if parsed_url.hostname not in ALLOWED_HOSTS:
        raise Exception(f"Host must be one of the following: {', '.join(ALLOWED_HOSTS)}")

    r = session.get(album_url, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        raise Exception(f"HTTP error {r.status_code}")

    soup = BeautifulSoup(r.content, "html.parser")
    title = soup.find("meta", property="og:title")["content"]

    # Extract video and image URLs using various attributes
    videos = [urljoin(album_url, video_source["src"]) for video_source in soup.find_all("source")]
    images = []
    for img in soup.find_all("img"):
        for attr in ["src", "data-src", "data-original", "data-lazy"]:
            if attr in img.attrs:
                images.append(urljoin(album_url, img[attr]))

    # Remove duplicates
    urls = list(set(videos + images))
    download_path = get_final_path(title)
    existing_files = get_files_in_dir(download_path)

    # Download files using multithreading
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(download, file_url, download_path, album_url, existing_files) for file_url in urls]
        for future in tqdm(futures, desc="Downloading files", ncols=100):
            future.result()  # Wait for all downloads to complete

def get_final_path(title):
    final_path = os.path.join("downloads", safe_file_name(title))
    if not os.path.isdir(final_path):
        os.makedirs(final_path)
    return final_path

def get_files_in_dir(directory):
    if not os.path.exists(directory):
        return []
    return [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]

def safe_file_name(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name)

def is_data_url(url):
    return url.startswith('data:')

def download(url, download_path, album=None, existing_files=[]):
    if is_data_url(url):
        return
    
    parsed_url = urlparse(url)
    file_name = safe_file_name(os.path.basename(parsed_url.path))
    if file_name in existing_files:
        print(f'[#] Skipping "{url}" [already downloaded]')
        return

    extracted = tldextract.extract(url)
    hostname = "{}.{}".format(extracted.domain, extracted.suffix)
    
    try:
        with session.get(
            url,
            headers={
                "Referer": album or f"https://{hostname}",
                "Origin": f"https://{hostname}",
                "User-Agent": "Mozilla/5.0",
            },
            stream=True,
        ) as r:
            r.raise_for_status()
            if 'content-type' in r.headers and not r.headers['content-type'].startswith(('image/', 'video/')):
                return
            
            # Check the content length header if available
            total_size = int(r.headers.get('content-length', 0))
            if total_size > 0 and total_size < 50 * 1024:  # Less than 50 KB
                return

            # Download the file
            with open(os.path.join(download_path, file_name), "wb") as f, tqdm(
                total=total_size, unit='B', unit_scale=True, desc=file_name, ncols=100, file=sys.stdout, leave=True
            ) as pbar:
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))
    except requests.RequestException as e:
        print(f'[ERROR] Download of "{url}" failed: {e}')

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download media from erome.com albums.")
    parser.add_argument("-u", help="URL of the album to download", type=str, required=True)
    args = parser.parse_args()
    collect_links(args.u)
