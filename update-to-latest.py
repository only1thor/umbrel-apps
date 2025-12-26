#!/usr/bin/env python3
"""
Simple script to update Docker images in docker-compose.yml to latest versions
Usage: python3 update-to-latest.py <docker-compose.yml>
"""

import sys
import re
import subprocess
import requests
from pathlib import Path
from typing import Optional, Tuple, List
from packaging import version

def get_docker_hub_tags(image_name: str) -> List[str]:
    """Get all tags for a Docker Hub image"""
    owner, repo = image_name.split('/')
    url = f"https://registry.hub.docker.com/v2/repositories/{owner}/{repo}/tags"
    
    tags = []
    while url:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            for tag_info in data.get('results', []):
                tag_name = tag_info.get('name')
                if tag_name:
                    tags.append(tag_name)
            
            url = data.get('next')
        except Exception as e:
            print(f"  Warning: Failed to fetch tags: {e}")
            return []
    
    return tags

def find_latest_version_tag(tags: List[str]) -> Optional[str]:
    """Find the latest semantic version tag from a list of tags"""
    version_tags = []
    
    for tag in tags:
        # Skip 'latest' and other non-version tags
        if tag in ['latest', 'edge', 'dev', 'develop', 'master', 'main']:
            continue
        
        # Try to extract version number (support v1.2.3 or 1.2.3 format)
        match = re.match(r'^v?(\d+\.\d+(?:\.\d+)?)', tag)
        if match:
            try:
                ver = version.parse(match.group(1))
                version_tags.append((tag, ver))
            except:
                continue
    
    if not version_tags:
        return None
    
    # Sort by version and return the latest
    version_tags.sort(key=lambda x: x[1], reverse=True)
    return version_tags[0][0]

def get_image_digest(image: str, tag: str) -> Optional[str]:
    """Pull image and get its digest using Docker CLI"""
    full_image = f"{image}:{tag}"
    try:
        print(f"  Pulling {full_image}...")
        result = subprocess.run(
            ["docker", "pull", full_image],
            capture_output=True,
            text=True,
            check=True
        )
        
        result = subprocess.run(
            ["docker", "inspect", full_image, "--format={{index .RepoDigests 0}}"],
            capture_output=True,
            text=True,
            check=True
        )
        
        repo_digest = result.stdout.strip()
        if "@" in repo_digest:
            return repo_digest.split("@")[1]
        return None
    except subprocess.CalledProcessError as e:
        print(f"  Error: {e.stderr}")
        return None

def parse_image_line(line: str) -> Optional[Tuple[str, str, str]]:
    """Parse image line from docker-compose.yml
    Returns: (image_name, tag, current_digest) or None
    """
    match = re.search(r'image:\s*([^:@\s]+/[^:@\s]+):([^@\s]+)(?:@(sha256:[a-f0-9]+))?', line)
    if match:
        image_name = match.group(1)
        tag = match.group(2)
        digest = match.group(3) or ""
        return (image_name, tag, digest)
    return None

def update_to_latest(compose_file: str, dry_run: bool = False):
    """Update docker-compose.yml images to latest versions"""
    
    path = Path(compose_file)
    if not path.exists():
        print(f"Error: File {compose_file} not found")
        sys.exit(1)
    
    print(f"Analyzing {compose_file}...\n")
    
    # Read file
    with open(path, 'r') as f:
        lines = f.readlines()
    
    # Track changes
    changes = []
    updated_lines = lines.copy()
    
    # Process each line
    for i, line in enumerate(lines):
        if 'image:' not in line:
            continue
        
        parsed = parse_image_line(line)
        if not parsed:
            continue
        
        image_name, current_tag, current_digest = parsed
        print(f"Processing: {image_name}:{current_tag}")
        
        # Get available tags
        print(f"  Fetching available tags...")
        tags = get_docker_hub_tags(image_name)
        
        if not tags:
            print(f"  ✗ Could not fetch tags, skipping")
            print()
            continue
        
        # Find latest version
        latest_tag = find_latest_version_tag(tags)
        
        if not latest_tag:
            print(f"  Warning: No semantic version tags found, using current tag")
            latest_tag = current_tag
        
        print(f"  Current tag: {current_tag}")
        print(f"  Latest tag:  {latest_tag}")
        
        # Get digest for latest version
        latest_digest = get_image_digest(image_name, latest_tag)
        
        if latest_digest:
            print(f"  Latest digest: {latest_digest}")
            
            if current_tag != latest_tag or current_digest != latest_digest:
                print(f"  ✓ Update available!")
                
                # Build new image line
                indent = len(line) - len(line.lstrip())
                new_line = f"{' ' * indent}image: {image_name}:{latest_tag}@{latest_digest}\n"
                updated_lines[i] = new_line
                
                changes.append({
                    'image': image_name,
                    'old_version': f"{current_tag}@{current_digest[:16]}..." if current_digest else current_tag,
                    'new_version': f"{latest_tag}@{latest_digest[:16]}..."
                })
            else:
                print(f"  ✓ Already on latest version")
        else:
            print(f"  ✗ Failed to fetch digest")
        
        print()
    
    # Save changes
    if changes and not dry_run:
        # Create backup
        backup_path = Path(f"{compose_file}.bak")
        with open(backup_path, 'w') as f:
            f.writelines(lines)
        print(f"Backup saved to {backup_path}")
        
        # Write updated file
        with open(path, 'w') as f:
            f.writelines(updated_lines)
        
        print(f"\n✓ Updated {len(changes)} image(s) in {compose_file}")
        for change in changes:
            print(f"  - {change['image']}")
            print(f"    {change['old_version']} → {change['new_version']}")
    elif changes:
        print(f"\nDry run: Would update {len(changes)} image(s)")
        for change in changes:
            print(f"  - {change['image']}")
            print(f"    {change['old_version']} → {change['new_version']}")
    else:
        print("✓ All images are already on latest versions")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 update-to-latest.py <docker-compose.yml> [--dry-run]")
        sys.exit(1)
    
    compose_file = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    
    if dry_run:
        print("Running in DRY RUN mode - no changes will be made\n")
    
    update_to_latest(compose_file, dry_run)
