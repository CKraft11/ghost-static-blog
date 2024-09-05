#!/usr/bin/env python3
import os
import sys
import subprocess

# Check if running as root
if os.geteuid() == 0:
    print("This script should not be run as root. Please run it as a regular user.")
    sys.exit(1)

# Check if running in a virtual environment
if sys.prefix == sys.base_prefix:
    print("This script should be run within a virtual environment.")
    print("Please activate your virtual environment and try again.")
    print("If you haven't set up a virtual environment, you can do so with these commands:")
    print("python3 -m venv /path/to/your/venv")
    print("source /path/to/your/venv/bin/activate")
    print("pip install pillow-avif-plugin requests beautifulsoup4 pillow gitpython")
    sys.exit(1)

# Check if required packages are installed
required_packages = ['pillow-avif-plugin', 'requests', 'beautifulsoup4', 'pillow', 'gitpython']
installed_packages = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze']).decode().split('\n')
installed_packages = [package.split('==')[0].lower() for package in installed_packages]

missing_packages = [package for package in required_packages if package.lower() not in installed_packages]

if missing_packages:
    print("The following required packages are missing:")
    for package in missing_packages:
        print(f"- {package}")
    print("Please install them using:")
    print(f"pip install {' '.join(missing_packages)}")
    sys.exit(1)

import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
import re
import shutil
import git
from PIL import Image
import concurrent.futures
import requests
from urllib.parse import urljoin, urlparse
import time
import mimetypes
import imghdr
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ImprovedGhostStaticGenerator:
    def __init__(self, source_url, target_url, repo_path):
        self.source_url = source_url
        self.target_url = target_url
        self.repo_path = repo_path
        self.public_dir = os.path.join(repo_path, 'public')
        self.visited_urls = set()
        self.file_urls = set()

    def update_repo(self):
        try:
            repo = git.Repo(self.repo_path)
            repo.git.fetch('origin')
            current_branch = repo.active_branch.name
            remote_branches = [ref.name for ref in repo.references if isinstance(ref, git.RemoteReference)]
            remote_branch = f'origin/{current_branch}'
            
            if remote_branch in remote_branches:
                repo.git.pull('origin', current_branch, '--ff-only')
            else:
                print(f"Warning: Remote branch '{remote_branch}' not found. Skipping pull operation.")
            
            print(f"Repository updated successfully on branch '{current_branch}'")
        except git.exc.GitCommandError as e:
            print(f"Git operation failed: {e}")
            print("Continuing with the rest of the script...")
        except Exception as e:
            print(f"An error occurred while updating the repository: {e}")
            print("Continuing with the rest of the script...")

    def scrape_site(self):
        self.scrape_url(self.source_url)

    def scrape_url(self, url):
        if url in self.visited_urls:
            return
        self.visited_urls.add(url)

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            content_type = response.headers.get('content-type', '').lower()
            if 'text/html' in content_type:
                self.process_html(url, response.text)
            elif any(type in content_type for type in ['text/css', 'javascript', 'image', 'application']):
                self.file_urls.add(url)
                self.save_file(url, response.content, os.path.splitext(urlparse(url).path)[1], is_binary=True)
            else:
                print(f"Skipping unsupported content type for {url}: {content_type}")

        except requests.exceptions.RequestException as e:
            print(f"Error fetching {url}: {e}")
        except Exception as e:
            print(f"Unexpected error scraping {url}: {str(e)}")

        time.sleep(0.1)

    def process_html(self, url, html_content):
        self.save_file(url, html_content, '.html')
        soup = BeautifulSoup(html_content, 'html.parser')
        
        for tag in soup.find_all(['a', 'link', 'script', 'img', 'source']):
            attr = tag.get('href') or tag.get('src') or tag.get('data-src')
            if attr:
                new_url = urljoin(url, attr)
                if self.is_same_domain(new_url):
                    self.scrape_url(new_url)

        # Process inline CSS and extract image URLs
        for style in soup.find_all('style'):
            css_content = style.string
            if css_content:
                image_urls = re.findall(r'url\([\'"]?([^\'"]+)[\'"]?\)', css_content)
                for img_url in image_urls:
                    full_url = urljoin(url, img_url)
                    if self.is_same_domain(full_url):
                        self.scrape_url(full_url)

        # Process inline style attributes
        for tag in soup.find_all(style=True):
            style_content = tag['style']
            image_urls = re.findall(r'url\([\'"]?([^\'"]+)[\'"]?\)', style_content)
            for img_url in image_urls:
                full_url = urljoin(url, img_url)
                if self.is_same_domain(full_url):
                    self.scrape_url(full_url)

    def is_same_domain(self, url):
        return urlparse(url).netloc == urlparse(self.source_url).netloc

    def save_file(self, url, content, extension, is_binary=False):
        parsed_url = urlparse(url)
        relative_path = parsed_url.path.lstrip('/')
        if not relative_path:
            relative_path = 'index.html'
        elif relative_path.endswith('/'):
            relative_path += 'index.html'
        
        file_path = os.path.join(self.public_dir, relative_path)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        mode = 'wb' if is_binary else 'w'
        with open(file_path, mode) as f:
            f.write(content)
        
        print(f"Saved: {file_path}")

    def convert_images(self):
        def process_image(img_path):
            try:
                img = Image.open(img_path)
                base_name = os.path.splitext(img_path)[0]
                
                # WebP conversion
                img.save(f"{base_name}.webp", 'WEBP')
                print(f"Converted to WebP: {img_path}")
                
                # AVIF conversion
                try:
                    # Use pillow-avif-plugin for AVIF support
                    img.save(f"{base_name}.avif", 'AVIF')
                    print(f"Converted to AVIF: {img_path}")
                except Exception as e:
                    print(f"Error converting to AVIF {img_path}: {str(e)}")
                
                # JXL conversion
                try:
                    subprocess.run(['cjxl', img_path, f"{base_name}.jxl"], check=True)
                    print(f"Converted to JXL: {img_path}")
                except subprocess.CalledProcessError as e:
                    print(f"Error converting to JXL {img_path}: {str(e)}")
                except FileNotFoundError:
                    print("cjxl command not found. Make sure JPEG XL tools are installed.")
                
            except Exception as e:
                print(f"Error processing {img_path}: {str(e)}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
            futures = []
            for root, _, files in os.walk(self.public_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    if imghdr.what(file_path) is not None:
                        futures.append(executor.submit(process_image, file_path))
            
            for future in concurrent.futures.as_completed(futures):
                future.result()

    def update_html_for_image_formats(self):
        for root, _, files in os.walk(self.public_dir):
            for file in files:
                if file.endswith('.html'):
                    file_path = os.path.join(root, file)
                    logging.info(f"Processing HTML file: {file_path}")
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    soup = BeautifulSoup(content, 'html.parser')
                    images_processed = 0
                    for img in soup.find_all('img'):
                        src = img.get('src') or img.get('data-src')
                        if not src:
                            logging.warning(f"Image without src found in {file_path}")
                            continue

                        logging.info(f"Processing image with src: {src}")

                        # Handle relative paths
                        if not src.startswith(('http://', 'https://', '//')):
                            src = '/' + src.lstrip('/')

                        original_srcset = img.get('srcset') or img.get('data-srcset', '')
                        sizes = img.get('sizes', '')

                        parent = img.parent
                        if parent.name != 'picture':
                            picture = soup.new_tag('picture')
                            img.wrap(picture)
                            logging.info("Created new picture tag")
                        else:
                            picture = parent
                            logging.info("Using existing picture tag")
                        
                        for source in picture.find_all('source'):
                            source.decompose()
                            logging.info("Removed existing source tag")
                        
                        formats = [('jxl', 'image/jxl'), ('avif', 'image/avif'), ('webp', 'image/webp')]
                        
                        sources = []
                        for format_ext, format_type in formats:
                            srcset = []
                            for src_entry in original_srcset.split(','):
                                src_entry = src_entry.strip()
                                if src_entry:
                                    parts = src_entry.split()
                                    if len(parts) == 2:
                                        orig_src, width = parts
                                        new_src = re.sub(r'\.[^.]+$', f'.{format_ext}', orig_src)
                                        local_path = self.url_to_local_path(new_src)
                                        if local_path and os.path.exists(local_path):
                                            srcset.append(f"{new_src} {width}")
                            
                            if srcset:
                                source = soup.new_tag('source', type=format_type)
                                source['srcset'] = ', '.join(srcset)
                                if sizes:
                                    source['sizes'] = sizes
                                sources.append(source)
                                logging.info(f"Created source for {format_type}")
                        
                        # Add sources in reverse order to ensure correct priority
                        for source in reversed(sources):
                            picture.insert(0, source)
                        
                        # Ensure lazy loading is on the img element
                        img['loading'] = 'lazy'
                        
                        images_processed += 1
                    
                    logging.info(f"Processed {images_processed} images in {file_path}")
                    
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(str(soup))
                    logging.info(f"Updated {file_path}")

    def url_to_local_path(self, url):
        if url.startswith('/'):
            return os.path.join(self.public_dir, url.lstrip('/'))
        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.netloc and parsed_url.netloc not in [urllib.parse.urlparse(self.source_url).netloc, urllib.parse.urlparse(self.target_url).netloc]:
            return None
        relative_path = parsed_url.path.lstrip('/')
        return os.path.join(self.public_dir, relative_path)

    def local_path_to_url(self, local_path, current_file_path):
        # Convert a local file path to a URL, handling both absolute and relative paths
        if local_path.startswith(self.public_dir):
            # Absolute path
            relative_path = os.path.relpath(local_path, self.public_dir)
            return urllib.parse.urljoin(self.target_url, relative_path.replace('\\', '/'))
        else:
            # Relative path
            relative_path = os.path.relpath(local_path, os.path.dirname(current_file_path))
            return relative_path.replace('\\', '/')

    def replace_urls_in_files(self):
        for root, _, files in os.walk(self.public_dir):
            for file in files:
                if file.endswith(('.html', '.css', '.js')):
                    file_path = os.path.join(root, file)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    content = content.replace(self.source_url, self.target_url)
                    
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)

    def commit_and_push(self):
        try:
            repo = git.Repo(self.repo_path)
            repo.git.add(A=True)
            repo.git.commit(m=f"Updated static site - {time.strftime('%Y-%m-%d %H:%M:%S')}")
            repo.git.push('origin', repo.active_branch.name)
            print("Changes committed and pushed successfully")
        except git.exc.GitCommandError as e:
            print(f"Git operation failed: {e}")
        except Exception as e:
            print(f"An error occurred while committing and pushing: {e}")
            
    def run(self):
        logging.info("Starting the static site generation process")
        self.update_repo()
        self.scrape_site()
        self.convert_images()
        self.update_html_for_image_formats()
        self.replace_urls_in_files()
        self.commit_and_push()
        logging.info("Static site generation process completed")

if __name__ == "__main__":
    source_url = "http://10.0.0.222:2368"  # Change this to your local Ghost URL
    target_url = "https://dev.cadenkraft.com"  # Change this to your target URL
    repo_path = "/home/ghost-static-site-gen"  # Change this to your local repo path

    generator = ImprovedGhostStaticGenerator(source_url, target_url, repo_path)
    generator.run()
