#!/usr/bin/env python3
import os
import sys
import subprocess
import argparse
import copy

# Check if running as root
if os.geteuid() == 0:
    print("This script should not be run as root. Please run it as a regular user.")
    sys.exit(1)

# Check if running in a virtual environment
if sys.prefix == sys.base_prefix:
    print("This script should be run within a virtual environment.")
    print("Please activate your virtual environment and try again.")
    print("If you haven't set up a virtual environment, you can do so with these commands:")
    print("python3 -m venv ghost-static-env")
    print("source ghost-static-env/bin/activate")
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
import shutil

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ImprovedGhostStaticGenerator:
    def __init__(self, source_url, target_url, repo_path, force_reconvert=False):
        self.source_url = source_url
        self.target_url = target_url
        self.repo_path = repo_path
        self.public_dir = os.path.join(repo_path, 'public')
        self.visited_urls = set()
        self.file_urls = set()
        self.force_reconvert = force_reconvert

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
        self.scrape_root_files()
    
    def scrape_root_files(self):
        root_files = [
            'favicon.ico',
            'robots.txt',
            'sitemap.xml',
            'sitemap-authors.xml',
            'sitemap-pages.xml',
            'sitemap-posts.xml',
            'sitemap-tags.xml'
        ]
        for file in root_files:
            url = urljoin(self.source_url, file)
            self.scrape_url(url)

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
                self.scrape_image_sizes(url)
                self.scrape_meta_images(url)  # Add this line
            elif 'image' in content_type:
                self.file_urls.add(url)
                self.save_file(url, response.content, os.path.splitext(urlparse(url).path)[1], is_binary=True)
            elif any(type in content_type for type in ['text/css', 'javascript', 'application']):
                self.file_urls.add(url)
                self.save_file(url, response.content, os.path.splitext(urlparse(url).path)[1], is_binary=True)
            else:
                logging.info(f"Saving file with content-type {content_type}: {url}")
                self.save_file(url, response.content, os.path.splitext(urlparse(url).path)[1], is_binary=True)
    
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching {url}: {e}")
        except Exception as e:
            logging.error(f"Unexpected error scraping {url}: {str(e)}")
    
        time.sleep(0.1)
        
    def scrape_meta_images(self, url):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching URL {url}: {e}")
            return
    
        meta_images = soup.find_all('meta', property=['og:image', 'twitter:image'])
        for meta in meta_images:
            img_url = meta.get('content')
            if img_url and self.is_same_domain(img_url):
                try:
                    img_response = requests.get(img_url, timeout=30)
                    if img_response.status_code == 200:
                        self.file_urls.add(img_url)
                        self.save_file(img_url, img_response.content, os.path.splitext(img_url)[1], is_binary=True)
                        logging.info(f"Scraped meta image: {img_url}")
                    else:
                        logging.warning(f"Failed to scrape meta image {img_url}: HTTP {img_response.status_code}")
                except requests.exceptions.RequestException as e:
                    logging.warning(f"Failed to scrape meta image {img_url}: {e}")

    def scrape_image_sizes(self, url):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching URL {url}: {e}")
            return
    
        for img in soup.find_all(['img', 'source']):
            srcset = img.get('srcset') or img.get('data-srcset', '')
            src = img.get('src') or img.get('data-src', '')
            
            all_urls = [src] if src else []
            all_urls.extend([s.split()[0] for s in srcset.split(',') if s.strip()])
            
            for img_url in all_urls:
                if img_url and self.is_same_domain(img_url):
                    try:
                        img_response = requests.get(img_url, timeout=30)
                        if img_response.status_code == 200:
                            self.file_urls.add(img_url)
                            self.save_file(img_url, img_response.content, os.path.splitext(img_url)[1], is_binary=True)
                            logging.info(f"Scraped image: {img_url}")
                        else:
                            logging.warning(f"Failed to scrape image {img_url}: HTTP {img_response.status_code}")
                    except requests.exceptions.RequestException as e:
                        logging.warning(f"Failed to scrape image {img_url}: {e}")
    
        # Also check for background images in inline styles
        for tag in soup.find_all(style=True):
            style = tag['style']
            urls = re.findall(r'url\([\'"]?([^\'"]+)[\'"]?\)', style)
            for img_url in urls:
                if self.is_same_domain(img_url):
                    try:
                        img_response = requests.get(img_url, timeout=30)
                        if img_response.status_code == 200:
                            self.file_urls.add(img_url)
                            self.save_file(img_url, img_response.content, os.path.splitext(img_url)[1], is_binary=True)
                            logging.info(f"Scraped background image: {img_url}")
                        else:
                            logging.warning(f"Failed to scrape background image {img_url}: HTTP {img_response.status_code}")
                    except requests.exceptions.RequestException as e:
                        logging.warning(f"Failed to scrape background image {img_url}: {e}")

    def scrape_iframe_content(self, iframe_src):
        if not self.is_same_domain(iframe_src):
            return
    
        try:
            response = requests.get(iframe_src, timeout=30)
            response.raise_for_status()
            iframe_content = response.text
    
            # Save the iframe HTML file
            self.save_file(iframe_src, iframe_content, '.html')
    
            # Parse the iframe content
            iframe_soup = BeautifulSoup(iframe_content, 'html.parser')
    
            # Find and scrape all script files
            for script in iframe_soup.find_all('script', src=True):
                script_src = urljoin(iframe_src, script['src'])
                if self.is_same_domain(script_src):
                    self.scrape_url(script_src)
    
            # Find and scrape all CSS files
            for link in iframe_soup.find_all('link', rel='stylesheet'):
                css_src = urljoin(iframe_src, link['href'])
                if self.is_same_domain(css_src):
                    self.scrape_url(css_src)
    
            # Find and scrape all images
            for img in iframe_soup.find_all('img', src=True):
                img_src = urljoin(iframe_src, img['src'])
                if self.is_same_domain(img_src):
                    self.scrape_url(img_src)
    
            # Look for any other resources that might be loaded dynamically
            # This is a simple regex search and might need to be adjusted based on your specific JS code
            resource_pattern = re.compile(r'(["\'`])((?:\.{1,2}\/)*(?:[\w-]+\/)*[\w-]+\.(?:jpg|jpeg|png|gif|svg|js|css))\1')
            for match in resource_pattern.finditer(iframe_content):
                resource_path = match.group(2)
                resource_url = urljoin(iframe_src, resource_path)
                if self.is_same_domain(resource_url):
                    self.scrape_url(resource_url)
    
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching iframe content from {iframe_src}: {e}")
    
    def copy_renders_folder(self):
        source_renders_path = '/helium/ghost/ghost-backup/content/renders/'
        destination_renders_path = os.path.join(self.public_dir, 'content', 'renders')
        
        # Make sure destination directory exists
        os.makedirs(destination_renders_path, exist_ok=True)
        
        # Track stats
        files_copied = 0
        files_skipped = 0
        
        try:
            # Walk through source directory
            for root, dirs, files in os.walk(source_renders_path):
                # Get the relative path from source
                rel_path = os.path.relpath(root, source_renders_path)
                dest_dir = os.path.join(destination_renders_path, rel_path)
                
                # Create destination directory if it doesn't exist
                os.makedirs(dest_dir, exist_ok=True)
                
                # Copy each file if it doesn't exist or is newer
                for file in files:
                    source_file = os.path.join(root, file)
                    dest_file = os.path.join(dest_dir, file)
                    
                    # Check if we need to copy
                    should_copy = False
                    if not os.path.exists(dest_file):
                        should_copy = True
                    else:
                        source_mtime = os.path.getmtime(source_file)
                        dest_mtime = os.path.getmtime(dest_file)
                        if source_mtime > dest_mtime:
                            should_copy = True
                    
                    if should_copy:
                        shutil.copy2(source_file, dest_file)
                        files_copied += 1
                        logging.info(f"Copied render file: {dest_file}")
                    else:
                        files_skipped += 1
            
            logging.info(f"Renders folder sync complete: {files_copied} files copied, {files_skipped} unchanged files")
            
        except Exception as e:
            logging.error(f"Error copying renders folder: {str(e)}")

    
    def process_html(self, url, html_content):
        self.save_file(url, html_content, '.html')
        soup = BeautifulSoup(html_content, 'html.parser')
        
        for tag in soup.find_all(['a', 'link', 'script', 'img', 'source']):
            attr = tag.get('href') or tag.get('src') or tag.get('data-src')
            if attr:
                new_url = urljoin(url, attr)
                if self.is_same_domain(new_url):
                    self.scrape_url(new_url)
    
        # Process iframes
        for iframe in soup.find_all('iframe'):
            iframe_src = iframe.get('src')
            if iframe_src:
                iframe_url = urljoin(url, iframe_src)
                if self.is_same_domain(iframe_url):
                    self.scrape_iframe_content(iframe_url)
                    # Update iframe src to use the target URL
                    iframe['src'] = self.update_url(iframe_url)
    
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
    
        # Update the HTML content with the modified iframe src
        updated_html = str(soup)
        self.save_file(url, updated_html, '.html')

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
        encoding = None if is_binary else 'utf-8'
        with open(file_path, mode, encoding=encoding) as f:
            f.write(content)
        
        logging.info(f"Saved: {file_path}")

    def convert_images(self):
        def convert_to_webp(img_path):
            output_path = f"{os.path.splitext(img_path)[0]}.webp"
            if os.path.exists(output_path) and not self.force_reconvert:
                logging.info(f"WebP already exists, skipping: {img_path}")
                return True
            try:
                subprocess.run(['cwebp', '-q', '80', img_path, '-o', output_path], check=True)
                logging.info(f"Converted to WebP: {img_path}")
                return True
            except subprocess.CalledProcessError as e:
                logging.error(f"Error converting {img_path} to WebP: {str(e)}")
                return False

        def convert_to_avif(img_path):
            output_path = f"{os.path.splitext(img_path)[0]}.avif"
            if os.path.exists(output_path) and not self.force_reconvert:
                logging.info(f"AVIF already exists, skipping: {img_path}")
                return True
            try:
                # Use 4 threads for AVIF conversion
                subprocess.run(['avifenc', '-s', '0', '-j', '4', '-d', '8', img_path, output_path], check=True)
                logging.info(f"Converted to AVIF: {img_path}")
                return True
            except subprocess.CalledProcessError as e:
                logging.error(f"Error converting {img_path} to AVIF: {str(e)}")
                return False

        def convert_to_jxl(img_path):
            output_path = f"{os.path.splitext(img_path)[0]}.jxl"
            if os.path.exists(output_path) and not self.force_reconvert:
                logging.info(f"JXL already exists, skipping: {img_path}")
                return True
            try:
                subprocess.run(['cjxl', img_path, output_path], check=True)
                logging.info(f"Converted to JXL: {img_path}")
                return True
            except subprocess.CalledProcessError as e:
                logging.error(f"Error converting {img_path} to JXL: {str(e)}")
                return False
            except FileNotFoundError:
                logging.error("cjxl command not found. Please ensure JPEG XL tools are installed.")
                return False

        def process_image(img_path):
            webp_success = convert_to_webp(img_path)
            avif_success = convert_to_avif(img_path)
            jxl_success = convert_to_jxl(img_path)
            return webp_success, avif_success, jxl_success

        image_paths = []
        for root, _, files in os.walk(self.public_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')) and (self.force_reconvert or not all(os.path.exists(f"{os.path.splitext(file_path)[0]}.{ext}") for ext in ['webp', 'avif', 'jxl'])):
                    image_paths.append(file_path)

        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
            futures = [executor.submit(process_image, img_path) for img_path in image_paths]
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
    
                    # Update Open Graph meta tags
                    og_image = soup.find('meta', property='og:image')
                    if og_image:
                        og_image['content'] = self.update_url(og_image['content'])
                        logging.info(f"Updated og:image: {og_image['content']}")
    
                    for img in soup.find_all('img'):
                        src = img.get('src') or img.get('data-src')
                        if not src:
                            logging.warning(f"Image without src found in {file_path}")
                            continue
    
                        logging.info(f"Processing image with src: {src}")
    
                        original_srcset = img.get('srcset') or img.get('data-srcset', '')
                        sizes = img.get('sizes', '')
    
                        # Update src and srcset to use target URL
                        img['src'] = self.update_url(src)
                        if original_srcset:
                            img['srcset'] = ', '.join([f"{self.update_url(s.split()[0])} {s.split()[1]}" if len(s.split()) > 1 else self.update_url(s) for s in original_srcset.split(',')])
    
                        # Create picture tag
                        picture = soup.new_tag('picture')
                        img.wrap(picture)
    
                        formats = [('webp', 'image/webp'), ('avif', 'image/avif'), ('jxl', 'image/jxl')]
    
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
                                            srcset.append(f"{self.update_url(new_src)} {width}")
                            
                            if srcset:
                                source = soup.new_tag('source', type=format_type)
                                source['srcset'] = ', '.join(srcset)
                                if sizes:
                                    source['sizes'] = sizes
                                picture.insert(0, source)
                                logging.info(f"Created source for {format_type}")
    
                        # Ensure all original attributes of the img tag are preserved
                        for attr, value in img.attrs.items():
                            if attr not in ['src', 'srcset', 'sizes', 'data-src', 'data-srcset']:
                                img[attr] = value
    
                        # Ensure lazy loading
                        img['loading'] = 'lazy'
                        
                        images_processed += 1
                    
                    logging.info(f"Processed {images_processed} images in {file_path}")
                    
                    # Update all URLs in the HTML content
                    content = self.update_all_urls(str(soup))
                    
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logging.info(f"Updated {file_path}")
    
    def update_url(self, url):
        return url.replace(self.source_url, self.target_url)
    
    def update_all_urls(self, content):
        return content.replace(self.source_url, self.target_url)

    def update_urls_in_all_files(self):
        for root, _, files in os.walk(self.public_dir):
            for file in files:
                file_path = os.path.join(root, file)
                _, file_extension = os.path.splitext(file)
                
                if file_extension.lower() in ['.html', '.xml', '.css', '.js', '.json']:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    updated_content = self.update_all_urls(content)
                    
                    # Update iframe src URLs
                    if file_extension.lower() == '.html':
                        soup = BeautifulSoup(updated_content, 'html.parser')
                        for iframe in soup.find_all('iframe'):
                            src = iframe.get('src')
                            if src:
                                iframe['src'] = self.update_url(src)
                        updated_content = str(soup)
                    
                    if updated_content != content:
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(updated_content)
                        logging.info(f"Updated URLs in {file_path}")

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
                    content = content.replace("helium", "cadenkraft.com")
                    
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
        self.copy_renders_folder()  # Now uses smart copy
        self.convert_images()       # Will only convert images that haven't been converted already
        self.update_html_for_image_formats()
        self.update_urls_in_all_files()
        self.commit_and_push()
        logging.info("Static site generation process completed")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate static site from Ghost blog")
    parser.add_argument("--force-reconvert", action="store_true", help="Force reconversion of all images")
    args = parser.parse_args()

    source_url = "http://helium:2368"  # Change this to your local Ghost URL
    target_url = "https://cadenkraft.com"  # Change this to your target URL
    repo_path = "/home/ghost-static-site-gen"  # Change this to your local repo path

    generator = ImprovedGhostStaticGenerator(source_url, target_url, repo_path, force_reconvert=args.force_reconvert)
    generator.run()
