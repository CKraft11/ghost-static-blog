import os
import subprocess
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

class ImprovedGhostStaticGenerator:
    def __init__(self, source_url, target_url, repo_path):
        self.source_url = source_url
        self.target_url = target_url
        self.repo_path = repo_path
        self.public_dir = os.path.join(repo_path, 'public')
        self.image_dir = os.path.join(self.public_dir, 'content', 'images')
        self.renders_dir = os.path.join(self.public_dir, 'content', 'renders')
        self.visited_urls = set()

    def run(self):
        self.update_repo()
        self.scrape_site()
        self.copy_images()
        self.convert_images()
        self.update_html_for_image_formats()
        self.commit_and_push()

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
            elif 'text/css' in content_type:
                self.save_file(url, response.text, '.css')
            elif 'javascript' in content_type:
                self.save_file(url, response.text, '.js')
            elif 'image' in content_type:
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
        
        for tag in soup.find_all(['a', 'link', 'script', 'img']):
            if tag.name == 'a' and tag.get('href'):
                new_url = urljoin(url, tag['href'])
                if self.is_same_domain(new_url):
                    self.scrape_url(new_url)
            elif tag.name in ['link', 'script'] and tag.get('src'):
                self.scrape_url(urljoin(url, tag['src']))
            elif tag.name == 'img' and tag.get('src'):
                self.scrape_url(urljoin(url, tag['src']))

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

    def copy_images(self):
        shutil.rmtree(self.image_dir, ignore_errors=True)
        shutil.rmtree(self.renders_dir, ignore_errors=True)
        shutil.copytree('/helium/ghost/ghost-backup/content/images', self.image_dir)
        shutil.copytree('/helium/ghost/ghost-backup/content/renders', self.renders_dir)

    def convert_images(self):
        def process_image(img_path):
            try:
                img = Image.open(img_path)
                base_name = os.path.splitext(img_path)[0]
                img.save(f"{base_name}.webp", 'WEBP')
                img.save(f"{base_name}.avif", 'AVIF')
                print(f"Converted: {img_path}")
            except Exception as e:
                print(f"Error converting {img_path}: {str(e)}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
            for root, _, files in os.walk(self.public_dir):
                for file in files:
                    if file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                        img_path = os.path.join(root, file)
                        executor.submit(process_image, img_path)

    def update_html_for_image_formats(self):
        for root, _, files in os.walk(self.public_dir):
            for file in files:
                if file.endswith('.html'):
                    file_path = os.path.join(root, file)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    soup = BeautifulSoup(content, 'html.parser')
                    for img in soup.find_all('img'):
                        src = img.get('src')
                        if src:
                            base_src = os.path.splitext(src)[0]
                            img['srcset'] = f"{base_src}.webp, {base_src}.avif"
                            img['onerror'] = f"this.onerror=null; this.src='{src}';"
                    
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(str(soup))

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

if __name__ == "__main__":
    source_url = "http://10.0.0.222:2368"  # Change this to your local Ghost URL
    target_url = "https://cadenkraft.com"  # Change this to your target URL
    repo_path = "/home/ghost-static-site-gen"  # Change this to your local repo path

    generator = ImprovedGhostStaticGenerator(source_url, target_url, repo_path)
    generator.run()