import argparse
import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import os
import tldextract
from tqdm import tqdm
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import random

session = requests.Session()

ALLOWED_HOSTS = ["www.erome.com", "nl.erome.com", "erome.fan"]

# Global variables to track file types and sizes
file_summary = {
    'images': 0,
    'videos': 0,
    'total_size': 0
}

def collect_links(album_url):
    parsed_url = urlparse(album_url)
    if parsed_url.hostname not in ALLOWED_HOSTS:
        raise Exception(f"Host must be one of the following: {', '.join(ALLOWED_HOSTS)}")

    try:
        r = session.get(album_url, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
    except requests.RequestException as e:
        print(f'[ERROR] Failed to fetch the album page: {e}')
        return

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

    # Use ThreadPoolExecutor for concurrent downloads
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(download, url, album_url, download_path, existing_files): url for url in urls}
        with tqdm(total=len(urls), desc="Downloading files", ncols=100, file=sys.stdout, leave=True) as pbar:
            for future in as_completed(future_to_url):
                try:
                    future.result()  # Wait for the download to complete
                except Exception as e:
                    print(f'[ERROR] Download failed: {e}')
                pbar.update(1)  # Update the overall progress bar

    # Print summary at the end
    print_summary(title)

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

def download(url, album_url, download_path, existing_files=[]):
    if is_data_url(url):
        return
    
    parsed_url = urlparse(url)
    file_name = safe_file_name(os.path.basename(parsed_url.path))
    if file_name in existing_files:
        return

    extracted = tldextract.extract(url)
    hostname = "{}.{}".format(extracted.domain, extracted.suffix)
    
    retries = 3
    while retries > 0:
        try:
            with session.get(
                url,
                headers={
                    "Referer": album_url,
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

                # Update global file summary
                if 'image/' in r.headers['content-type']:
                    file_summary['images'] += 1
                elif 'video/' in r.headers['content-type']:
                    file_summary['videos'] += 1
                file_summary['total_size'] += total_size

                # Download the file without individual progress bars
                with open(os.path.join(download_path, file_name), "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:
                            f.write(chunk)
            break  # Exit the retry loop if successful
        except (requests.RequestException, IOError) as e:
            retries -= 1
            if retries > 0:
                wait = random.uniform(1, 3)
                print(f'[WARN] Download failed for "{url}". Retrying in {wait:.2f} seconds...')
                time.sleep(wait)
            else:
                print(f'[ERROR] Download failed for "{url}". No more retries.')

def print_summary(title):
    print("\nSummary:")
    print(f"Folder: {safe_file_name(title)}")
    print(f"Total size: {file_summary['total_size'] / (1024 * 1024):.2f} MB")
    print(f"Images: {file_summary['images']}")
    print(f"Videos: {file_summary['videos']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download media from erome.com albums.")
    parser.add_argument("-u", help="URL of the album to download", type=str, required=True)
    args = parser.parse_args()
    collect_links(args.u)
