#!/usr/bin/env python3
# encoding: utf-8
"""
munki_rebrand_swift.py

Script to rebrand and customise Munki's Managed Software Center (Munki 7+)
Compatible with macOS 26
"""

import subprocess
import os
import stat
import shutil
from tempfile import mkdtemp
from xml.etree import ElementTree as ET
import plistlib
import argparse
import sys
import atexit
import glob
import fnmatch
import io
import json
import getpass
import hashlib
import uuid

VERSION = "7.19"

APPNAME_LOCALIZED = {
    "Base": "Managed Software Center",
    "da": "Managed Software Center",
    "de": "Geführte Softwareaktualisierung", 
    "en": "Managed Software Center",
    "en-AU": "Managed Software Centre",
    "en-GB": "Managed Software Centre",
    "en-CA": "Managed Software Centre",
    "en_AU": "Managed Software Centre",
    "en_GB": "Managed Software Centre", 
    "en_CA": "Managed Software Centre",
    "es": "Centro de aplicaciones",
    "fi": "Managed Software Center",
    "fr": "Centre de gestion des logiciels",
    "it": "Centro Gestione Applicazioni",
    "ja": "Managed Software Center",
    "nb": "Managed Software Center",
    "nl": "Managed Software Center",
    "ru": "Центр Управления ПО",
    "sv": "Managed Software Center",
}

MUNKI_PATH = "usr/local/munki"
PY_FWK = os.path.join(MUNKI_PATH, "Python.Framework")
PY_CUR = os.path.join(PY_FWK, "Versions/Current")

ICON_SIZES = [
    ("16", "16x16"),
    ("32", "16x16@2x"),
    ("32", "32x32"),
    ("64", "32x32@2x"),
    ("128", "128x128"),
    ("256", "128x128@2x"),
    ("256", "256x256"),
    ("512", "256x256@2x"),
    ("512", "512x512"),
    ("1024", "512x512@2x"),
]

PKGBUILD = "/usr/bin/pkgbuild"
PKGUTIL = "/usr/sbin/pkgutil"
PRODUCTBUILD = "/usr/bin/productbuild"
PRODUCTSIGN = "/usr/bin/productsign"
CODESIGN = "/usr/bin/codesign"
FILE = "/usr/bin/file"
PLUTIL = "/usr/bin/plutil"
SIPS = "/usr/bin/sips"
ICONUTIL = "/usr/bin/iconutil"
CURL = "/usr/bin/curl"
ACTOOL = [
    "/usr/bin/actool",
    "/Applications/Xcode.app/Contents/Developer/usr/bin/actool",
]

MUNKIURL = "https://api.github.com/repos/munki/munki/releases/latest"
MUNKIBETAURL = "https://api.github.com/repos/munki/munki/releases"

global verbose
verbose = False
tmp_dir = mkdtemp()

# Global variables for icon handling
icns = None
car = None

@atexit.register
def cleanup():
    print("Cleaning up...")
    try:
        shutil.rmtree(tmp_dir)
    except OSError:
        pass
    print("Done.")

def run_cmd(cmd, ret=None):
    """Runs a command passed in as a list."""
    proc = subprocess.run(cmd, capture_output=True)
    if verbose and proc.stdout != b"" and not ret:
        print(proc.stdout.rstrip().decode())
    if proc.returncode != 0:
        print(proc.stderr.rstrip().decode())
        sys.exit(1)
    if ret:
        return proc.stdout.rstrip().decode()

def get_latest_munki_url(beta=False):
    """Get the latest Munki release URL, optionally including betas"""
    if beta:
        cmd = [CURL, "-s", MUNKIBETAURL]
        j = run_cmd(cmd, ret=True)
        releases = json.loads(j)
        
        # Find the latest beta (prerelease) version
        for release in releases:
            if release.get("prerelease", False):
                print(f"Found beta: {release['tag_name']}")
                return release["assets"][0]["browser_download_url"]
        
        print("No beta found, falling back to latest stable")
        cmd = [CURL, "-s", MUNKIURL]
        j = run_cmd(cmd, ret=True)
        api_result = json.loads(j)
        return api_result["assets"][0]["browser_download_url"]
    else:
        cmd = [CURL, "-s", MUNKIURL]
        j = run_cmd(cmd, ret=True)
        api_result = json.loads(j)
        return api_result["assets"][0]["browser_download_url"]

def download_pkg(url, output):
    print(f"Downloading munkitools from {url}...")
    cmd = [CURL, "--location", "--output", output, url]
    run_cmd(cmd)

def flatten_pkg(directory, pkg):
    """Flattens a pkg folder"""
    cmd = [PKGUTIL, "--flatten-full", directory, pkg]
    run_cmd(cmd)

def expand_pkg(pkg, directory):
    """Expands a flat pkg to a folder"""
    cmd = [PKGUTIL, "--expand-full", pkg, directory]
    run_cmd(cmd)

def plist_to_xml(plist):
    """Converts plist file to xml1 format"""
    cmd = [PLUTIL, "-convert", "xml1", plist]
    run_cmd(cmd)

def plist_to_binary(plist):
    """Converts plist file to binary1 format"""
    cmd = [PLUTIL, "-convert", "binary1", plist]
    run_cmd(cmd)

def guess_encoding(f):
    cmd = [FILE, "--brief", "--mime-encoding", f]
    enc = run_cmd(cmd, ret=True)
    if "ascii" in enc:
        return "utf-8"
    return enc

def is_binary(f):
    return guess_encoding(f) == "binary"

def is_signable_bin(path):
    '''Checks if a path is a file and is executable'''
    if os.path.isfile(path) and (os.stat(path).st_mode & stat.S_IXUSR > 0):
        return True
    return False

def is_signable_lib(path):
    '''Checks if a path is a file and ends with .so or .dylib'''
    if os.path.isfile(path) and (path.endswith(".so") or path.endswith(".dylib")):
        return True
    return False

def replace_strings(strings_file, code, appname):
    """EXACT COPY from original script - replaces localized app name in a .strings file with desired app name"""
    localized = APPNAME_LOCALIZED[code]
    if verbose:
        print(f"Replacing '{localized}' in {strings_file} with '{appname}'...")
    backup_file = f"{strings_file}.bak"
    enc = guess_encoding(strings_file)

    # Could do this in place but im oldskool so
    with io.open(backup_file, "w", encoding=enc) as fw, io.open(
        strings_file, "r", encoding=enc
    ) as fr:
        for line in fr:
            # We want to only replace on the right hand side of any =
            # and we don't want to do it to a comment
            if "=" in line and not line.startswith("/*"):
                left, right = line.split("=")
                right = right.replace(localized, appname)
                line = "=".join([left, right])
            fw.write(line)
    os.remove(strings_file)
    os.rename(backup_file, strings_file)

def icon_test(png):
    with open(png, "rb") as f:
        pngbin = f.read()
    if pngbin[:8] == b'\x89PNG\r\n\x1a\n' and pngbin[12:16] == b'IHDR':
        return True
    return False

def convert_to_icns_and_car(png, output_dir, actool=""):
    """Takes a png file and converts it to both icns and car formats"""
    icon_dir = os.path.join(output_dir, "icons")
    os.mkdir(icon_dir)
    
    # Create a temporary iconset folder (not inside Assets.xcassets)
    iconset = os.path.join(icon_dir, "AppIcon.iconset")
    os.mkdir(iconset)
    
    print("  Generating icon sizes...")
    for hw, suffix in ICON_SIZES:
        output_png = os.path.join(iconset, f"icon_{suffix}.png")
        cmd = [
            SIPS,
            "-z",
            hw,
            hw,
            png,
            "--out",
            output_png,
        ]
        run_cmd(cmd)
    
    # Create the icns file using iconutil
    print("  Creating .icns file...")
    icnspath = os.path.join(icon_dir, "AppIcon.icns")
    cmd = [ICONUTIL, "-c", "icns", iconset, "-o", icnspath]
    run_cmd(cmd)
    
    # Now create Assets.xcassets structure for actool
    if actool:
        print("  Creating Assets.car file...")
        
        # Create the proper Assets.xcassets structure
        xcassets = os.path.join(icon_dir, "Assets.xcassets")
        os.mkdir(xcassets)
        
        appiconset = os.path.join(xcassets, "AppIcon.appiconset")
        os.mkdir(appiconset)
        
        # Copy the generated PNGs to the appiconset
        for hw, suffix in ICON_SIZES:
            src = os.path.join(iconset, f"icon_{suffix}.png")
            dst = os.path.join(appiconset, f"AppIcon_{suffix}.png")
            shutil.copy2(src, dst)
        
        # Create the Contents.json for the appiconset
        contents = {
            "images": [],
            "info": {
                "author": "xcode",
                "version": 1
            }
        }
        
        for hw, suffix in ICON_SIZES:
            if suffix.endswith("@2x"):
                scale = "2x"
                size = str(int(int(hw) / 2))
            else:
                scale = "1x"
                size = hw
            
            image = {
                "size": f"{size}x{size}",
                "idiom": "mac",
                "filename": f"AppIcon_{suffix}.png",
                "scale": scale
            }
            contents["images"].append(image)
        
        # Write Contents.json
        with open(os.path.join(appiconset, "Contents.json"), 'w') as f:
            json.dump(contents, f, indent=2)
        
        # Create a partial info plist file
        partial_info_plist = os.path.join(icon_dir, "Info.plist")
        
        # Run actool to compile Assets.car with the required parameter
        cmd = [
            actool,
            "--compile",
            icon_dir,
            "--app-icon",
            "AppIcon",
            "--minimum-deployment-target",
            "10.11",
            "--output-partial-info-plist",
            partial_info_plist,
            "--platform",
            "macosx",
            xcassets,
        ]
        
        # Run actool and capture output
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"    actool error: {result.stderr}")
        
        if verbose and result.stdout:
            print(result.stdout)
        
        carpath = os.path.join(icon_dir, "Assets.car")
        if os.path.isfile(carpath):
            car_size = os.path.getsize(carpath)
            print(f"    Assets.car created: {car_size} bytes")
        else:
            carpath = None
            print("    Warning: Assets.car not created")
    else:
        print("    Warning: actool not found, Assets.car not created")
        carpath = None
    
    # Clean up the iconset
    shutil.rmtree(iconset)
    
    if not os.path.isfile(icnspath):
        icnspath = None
    
    return icnspath, carpath

def remove_signature(app_path):
    """Remove code signature from app"""
    if os.path.exists(app_path):
        cmd = [CODESIGN, "--remove-signature", app_path]
        try:
            run_cmd(cmd)
            print(f"  Removed signature from {os.path.basename(app_path)}")
        except:
            print(f"  Warning: Could not remove signature from {app_path}")

def sign_binary(signing_id, binary, verbose=False, deep=False, options=[], entitlements="", force=False):
    """EXACT COPY from original script - Signs a binary with a signing id, with optional arguments for command line args"""
    cmd = [CODESIGN, "--sign", signing_id]
    if force:
        cmd.append("--force")
    if deep:
        cmd.append("--deep")
    if verbose:
        cmd.append("--verbose")
    if entitlements:
        cmd.append("--entitlements")
        cmd.append(entitlements)
    if options:
        cmd.append("--options")
        cmd.append(",".join([option for option in options]))
    cmd.append(binary)
    run_cmd(cmd)

def sign_app(app_path, signing_id=None):
    """Re-sign application with proper entitlements for Swift apps"""
    if not os.path.exists(app_path):
        return False
    
    # First verify the app bundle structure
    if not verify_app_structure(app_path):
        print(f"ERROR: App bundle {app_path} has invalid structure, cannot sign")
        return False
    
    # Create basic entitlements for Swift apps
    entitlements = {
        "com.apple.security.cs.allow-unsigned-executable-memory": True,
        "com.apple.security.cs.allow-dyld-environment-variables": True,
        "com.apple.security.cs.disable-library-validation": True,
    }
    
    ent_file = os.path.join(tmp_dir, "entitlements.plist")
    with open(ent_file, 'wb') as f:
        plistlib.dump(entitlements, f)
    
    if signing_id:
        cmd = [CODESIGN, "--deep", "--force", "--entitlements", ent_file, 
               "--options", "runtime", "--sign", signing_id, app_path]
    else:
        # Ad-hoc sign
        cmd = [CODESIGN, "--deep", "--force", "--entitlements", ent_file,
               "--options", "runtime", "--sign", "-", app_path]
    
    try:
        run_cmd(cmd)
        print(f"  Successfully signed {os.path.basename(app_path)}")
        return True
    except Exception as e:
        print(f"Warning: Could not sign {app_path}: {e}")
        return False

def sign_package(signing_id, pkg):
    """EXACT COPY from original script - Signs a pkg with a signing id"""
    cmd = [PRODUCTSIGN, "--sign", signing_id, pkg, f"{pkg}-signed"]
    print("Signing pkg...")
    run_cmd(cmd)
    print(f"Moving {pkg}-signed to {pkg}...")
    os.rename(f"{pkg}-signed", pkg)

def update_app_display_name(app_path, new_name):
    """Update the app's display name in Info.plist"""
    info_plist = os.path.join(app_path, "Contents/Info.plist")
    if os.path.isfile(info_plist):
        try:
            with open(info_plist, 'rb') as f:
                plist = plistlib.load(f)
            
            plist['CFBundleDisplayName'] = new_name
            plist['CFBundleName'] = new_name
            
            with open(info_plist, 'wb') as f:
                plistlib.dump(plist, f)
                
            if verbose:
                print(f"  Updated display name to '{new_name}'")
                
        except Exception as e:
            print(f"Warning: Could not update Info.plist for {app_path}: {e}")

def create_custom_bundle_identifier(app_path, new_name):
    """Create a completely custom bundle identifier for macOS 26 compatibility"""
    info_plist = os.path.join(app_path, "Contents/Info.plist")
    if os.path.isfile(info_plist):
        try:
            with open(info_plist, 'rb') as f:
                plist = plistlib.load(f)
            
            # Generate a unique identifier
            unique_id = hashlib.md5(f"{new_name}_{uuid.uuid4()}".encode()).hexdigest()[:12]
            new_bundle_id = f"custom.munki.rebrand.{unique_id}"
            
            plist['CFBundleIdentifier'] = new_bundle_id
            
            # Update URL handlers if they exist
            if 'CFBundleURLTypes' in plist:
                for url_type in plist['CFBundleURLTypes']:
                    if 'CFBundleURLName' in url_type:
                        url_type['CFBundleURLName'] = new_bundle_id
            
            with open(info_plist, 'wb') as f:
                plistlib.dump(plist, f)
                
            print(f"  Updated CFBundleIdentifier to: {new_bundle_id}")
            return new_bundle_id
                
        except Exception as e:
            print(f"Warning: Could not update bundle identifier for {app_path}: {e}")
    return None

def rename_app_bundle_safe(app_pkg, old_path, new_path):
    """Safely rename the .app bundle using ditto to preserve all metadata"""
    old_app_dir = os.path.join(app_pkg, old_path)
    new_app_dir = os.path.join(app_pkg, new_path)
    
    if not os.path.exists(old_app_dir):
        if verbose:
            print(f"App not found: {old_app_dir}")
        return False
    
    if os.path.exists(new_app_dir):
        if verbose:
            print(f"Target already exists: {new_app_dir}")
        return True
    
    print(f"Copying app bundle: {os.path.basename(old_app_dir)} -> {os.path.basename(new_app_dir)}")
    
    # Create parent directory
    os.makedirs(os.path.dirname(new_app_dir), exist_ok=True)
    
    # Use ditto to preserve all attributes
    cmd = ["ditto", old_app_dir, new_app_dir]
    try:
        run_cmd(cmd)
        print(f"  Copy completed, verifying...")
        
        # Verify the copy
        if not verify_app_structure(new_app_dir):
            print(f"  ERROR: Copied app has invalid structure")
            return False
        
        print(f"  Copy verified, removing original...")
        shutil.rmtree(old_app_dir)
        
        return True
    except Exception as e:
        print(f"  ERROR during copy: {e}")
        return False

def get_dir_size(path):
    """Calculate total size of a directory"""
    total = 0
    for root, dirs, files in os.walk(path):
        for file in files:
            file_path = os.path.join(root, file)
            if os.path.isfile(file_path) and not os.path.islink(file_path):
                total += os.path.getsize(file_path)
    return total

def verify_app_structure(app_path):
    """Verify that the app bundle has the required structure"""
    required_paths = [
        "Contents/Info.plist",
        "Contents/MacOS",
        "Contents/Resources",
    ]
    
    missing = []
    for req_path in required_paths:
        full_path = os.path.join(app_path, req_path)
        if not os.path.exists(full_path):
            missing.append(req_path)
    
    if missing:
        if verbose:
            print(f"  Missing required paths: {', '.join(missing)}")
        return False
    
    # Check for executable in MacOS folder
    macos_dir = os.path.join(app_path, "Contents/MacOS")
    executables = []
    for item in os.listdir(macos_dir):
        item_path = os.path.join(macos_dir, item)
        if os.path.isfile(item_path) and os.access(item_path, os.X_OK):
            executables.append(item)
    
    if not executables:
        if verbose:
            print(f"  No executable found in Contents/MacOS")
        return False
    
    return True

def debug_app_bundle(app_path):
    """Print debug info about an app bundle"""
    print(f"\nDebug info for: {app_path}")
    print(f"  Exists: {os.path.exists(app_path)}")
    
    if not os.path.exists(app_path):
        return
    
    # Check if it's a symlink
    if os.path.islink(app_path):
        print(f"  Is symlink to: {os.readlink(app_path)}")
        return
    
    # Check size
    size = get_dir_size(app_path)
    print(f"  Total size: {size / (1024*1024):.2f} MB")
    
    # List contents
    contents_dir = os.path.join(app_path, "Contents")
    if os.path.exists(contents_dir):
        print(f"  Contents of Contents:")
        for item in sorted(os.listdir(contents_dir)):
            item_path = os.path.join(contents_dir, item)
            if os.path.isdir(item_path):
                item_size = get_dir_size(item_path)
                print(f"    {item}/ - {item_size / (1024*1024):.2f} MB")
            else:
                item_size = os.path.getsize(item_path) if os.path.isfile(item_path) else 0
                print(f"    {item} - {item_size / 1024:.1f} KB")
    
    # Check Info.plist
    info_plist = os.path.join(contents_dir, "Info.plist")
    if os.path.exists(info_plist):
        try:
            with open(info_plist, 'rb') as f:
                plist = plistlib.load(f)
            print(f"  CFBundleIdentifier: {plist.get('CFBundleIdentifier', 'Not set')}")
            print(f"  CFBundleName: {plist.get('CFBundleName', 'Not set')}")
            print(f"  CFBundleDisplayName: {plist.get('CFBundleDisplayName', 'Not set')}")
            print(f"  CFBundleExecutable: {plist.get('CFBundleExecutable', 'Not set')}")
            print(f"  CFBundleVersion: {plist.get('CFBundleVersion', 'Not set')}")
            print(f"  CFBundleShortVersionString: {plist.get('CFBundleShortVersionString', 'Not set')}")
        except:
            print(f"  Could not read Info.plist")

def get_version_from_package(root_dir):
    """Extract the actual version from the package"""
    # First try to get version from the main app's Info.plist
    for item in os.listdir(root_dir):
        if item.startswith("munkitools_app"):
            app_pkg = os.path.join(root_dir, item)
            payload_dir = os.path.join(app_pkg, "Payload")
            apps_dir = os.path.join(payload_dir, "Applications")
            if os.path.exists(apps_dir):
                for app in os.listdir(apps_dir):
                    if app.endswith('.app'):
                        info_plist = os.path.join(apps_dir, app, "Contents/Info.plist")
                        if os.path.exists(info_plist):
                            try:
                                with open(info_plist, 'rb') as f:
                                    plist = plistlib.load(f)
                                version = plist.get('CFBundleShortVersionString')
                                if version:
                                    return version
                            except:
                                pass
    
    # Fallback to Distribution file
    distfile = os.path.join(root_dir, "Distribution")
    if os.path.exists(distfile):
        try:
            with open(distfile, 'r') as f:
                content = f.read()
                # Look for version in the Distribution file
                import re
                match = re.search(r'version="([0-9.]+)"', content)
                if match:
                    return match.group(1)
        except:
            pass
    
    return "7.0.8"  # Default fallback

def process_apps_for_macos26(app_pkg, appname, icon_file=None, signing_id=None, actool=None):
    """Process apps with macOS 26 compatible approach"""
    
    apps_processed = 0
    sanitized_name = appname.replace("/", "-").replace("\\", "-")
    
    # Find all .app bundles in the package
    payload_dir = os.path.join(app_pkg, "Payload")
    if not os.path.exists(payload_dir):
        print(f"  No Payload directory found in {app_pkg}")
        return 0
    
    # First, find the main Managed Software Center app
    main_app_path = None
    main_app_dir = None
    
    # Look for the main app in Applications folder
    apps_dir = os.path.join(payload_dir, "Applications")
    if os.path.exists(apps_dir):
        for item in os.listdir(apps_dir):
            if item == "Managed Software Center.app":
                main_app_path = os.path.join(apps_dir, item)
                main_app_dir = apps_dir
                break
    
    if not main_app_path:
        print(f"  Could not find Managed Software Center.app")
        return 0
    
    print(f"Processing {os.path.basename(main_app_path)}...")
    
    # Debug original app
    if verbose:
        debug_app_bundle(main_app_path)
    
    # Rename the main app
    new_main_app_path = os.path.join(main_app_dir, f"{sanitized_name}.app")
    
    if main_app_path != new_main_app_path:
        print(f"  Renaming main app to {sanitized_name}.app")
        
        # Remove any existing destination
        if os.path.exists(new_main_app_path):
            shutil.rmtree(new_main_app_path)
        
        # Use ditto to copy preserving all metadata
        cmd = ["ditto", main_app_path, new_main_app_path]
        run_cmd(cmd)
        
        # Verify the copy
        if verify_app_structure(new_main_app_path):
            # Remove original
            shutil.rmtree(main_app_path)
            main_app_path = new_main_app_path
        else:
            print(f"  ERROR: Copied app is invalid, keeping original")
            # Clean up failed copy
            if os.path.exists(new_main_app_path):
                shutil.rmtree(new_main_app_path)
    
    # Process the main app
    process_single_app(main_app_path, appname, icon_file, signing_id, actool)
    apps_processed += 1
    
    # Now find and process helper apps (they're inside the main app bundle)
    helpers_dir = os.path.join(main_app_path, "Contents/Helpers")
    if os.path.exists(helpers_dir):
        for helper_name in os.listdir(helpers_dir):
            helper_path = os.path.join(helpers_dir, helper_name)
            
            # Check if it's a symlink
            if os.path.islink(helper_path):
                print(f"  Helper {helper_name} is a symlink, updating symlink target...")
                # Update symlink to point to the new app name if needed
                target = os.readlink(helper_path)
                if "Managed Software Center.app" in target:
                    new_target = target.replace("Managed Software Center.app", f"{sanitized_name}.app")
                    os.remove(helper_path)
                    os.symlink(new_target, helper_path)
                    print(f"    Updated symlink from {target} to {new_target}")
                continue
                
            if helper_name.endswith('.app') and os.path.isdir(helper_path):
                print(f"Processing helper: {helper_name}")
                
                if verbose:
                    debug_app_bundle(helper_path)
                
                process_single_app(helper_path, appname, icon_file, signing_id, actool)
                apps_processed += 1
    
    return apps_processed

def process_single_app(app_path, appname, icon_file=None, signing_id=None, actool=None):
    """Process a single app bundle"""
    
    # Skip if it's a symlink
    if os.path.islink(app_path):
        print(f"  Skipping symlink: {app_path}")
        return
    
    # Verify structure before processing
    if not verify_app_structure(app_path):
        print(f"  WARNING: App {app_path} has invalid structure, skipping processing")
        return
    
    # Remove signature before modifications
    remove_signature(app_path)
    
    # Update display name in Info.plist
    update_app_display_name(app_path, appname)
    
    # Create custom bundle identifier
    create_custom_bundle_identifier(app_path, appname)
    
    # Update localized strings
    resources_dir = os.path.join(app_path, "Contents/Resources")
    if os.path.exists(resources_dir):
        lproj_dirs = glob.glob(os.path.join(resources_dir, "*.lproj"))
        for lproj_dir in lproj_dirs:
            code = os.path.basename(lproj_dir).split(".")[0]
            if code in list(APPNAME_LOCALIZED.keys()):
                for root, dirs, files in os.walk(lproj_dir):
                    for file_ in files:
                        lfile = os.path.join(root, file_)
                        if fnmatch.fnmatch(lfile, "*.strings"):
                            replace_strings(lfile, code, appname)
    
    # Handle icon replacement - for macOS 26, we need to replace Assets.car
    if icon_file and icns and car and os.path.isfile(car):
        # Replace Assets.car (this is what macOS 26 uses)
        car_path = os.path.join(app_path, "Contents/Resources/Assets.car")
        if os.path.isfile(car_path):
            original_size = os.path.getsize(car_path)
            new_size = os.path.getsize(car)
            print(f"  Original Assets.car size: {original_size} bytes")
            print(f"  New Assets.car size: {new_size} bytes")
            
            # Only replace if the new car is reasonably sized
            if new_size > 100000:  # At least 100KB
                print(f"  Replacing Assets.car with custom icon...")
                # Backup original just in case
                backup_path = car_path + ".backup"
                shutil.copy2(car_path, backup_path)
                
                # Replace with new car
                shutil.copy2(car, car_path)
                
                # Verify the replacement
                if os.path.getsize(car_path) == new_size:
                    print(f"    Assets.car replaced successfully")
                    # Remove backup
                    os.remove(backup_path)
                else:
                    print(f"    ERROR: Assets.car replacement failed, restoring backup")
                    shutil.copy2(backup_path, car_path)
            else:
                print(f"  WARNING: New Assets.car too small ({new_size} bytes)")
                print(f"  Keeping original Assets.car to preserve app functionality")
        
        # Also replace .icns files as backup
        icon_path = os.path.join(app_path, "Contents/Resources/AppIcon.icns")
        if os.path.isfile(icon_path):
            print(f"  Also replacing AppIcon.icns as backup...")
            shutil.copy2(icns, icon_path)
    
    # Re-sign the app
    sign_app(app_path, signing_id)

def sign_all_binaries(signing_id, root_dir, appname):
    """Comprehensive binary signing"""
    print("Signing binaries (this may take a while)...")
    
    # Find all packages
    app_pkgs = glob.glob(os.path.join(root_dir, "munkitools_app*"))
    if not app_pkgs:
        print("No app packages found for signing")
        return
    
    app_pkg = app_pkgs[0]
    core_pkgs = glob.glob(os.path.join(root_dir, "munkitools_core*"))
    python_pkgs = glob.glob(os.path.join(root_dir, "munkitools_python*"))
    
    if not core_pkgs or not python_pkgs:
        print("Warning: Could not find all required packages for signing")
        return
    
    core_pkg = core_pkgs[0]
    python_pkg = python_pkgs[0]

    app_payload = os.path.join(app_pkg, "Payload")
    core_payload = os.path.join(core_pkg, "Payload")
    python_payload = os.path.join(python_pkg, "Payload")

    # Generate entitlements file
    entitlements = {
        "com.apple.security.cs.allow-unsigned-executable-memory": True
    }
    ent_file = os.path.join(tmp_dir, "entitlements.plist")
    with open(ent_file, 'wb') as f:
        plistlib.dump(entitlements, f)

    sanitized_name = appname.replace("/", "-").replace("\\", "-")
    
    # Find the actual app path
    app_path = None
    if os.path.exists(app_payload):
        apps_dir = os.path.join(app_payload, "Applications")
        if os.path.exists(apps_dir):
            for item in os.listdir(apps_dir):
                if item.endswith('.app'):
                    app_path = os.path.join(apps_dir, item)
                    break
    
    if not app_path:
        print("Could not find app for signing")
        return
    
    # Build list of binaries to sign
    binaries = []
    
    # DockTile plugin
    plugin_path = os.path.join(app_path, "Contents/PlugIns/MSCDockTilePlugin.docktileplugin")
    if os.path.exists(plugin_path):
        binaries.append(plugin_path)
    
    # Helper apps (only actual bundles, not symlinks)
    helpers_dir = os.path.join(app_path, "Contents/Helpers")
    if os.path.exists(helpers_dir):
        for helper in os.listdir(helpers_dir):
            helper_path = os.path.join(helpers_dir, helper)
            if helper.endswith('.app') and os.path.isdir(helper_path) and not os.path.islink(helper_path):
                binaries.append(helper_path)
    
    # Main app
    binaries.append(app_path)
    
    # managedsoftwareupdate
    msu = os.path.join(core_payload, MUNKI_PATH, "managedsoftwareupdate")
    if os.path.exists(msu) and is_binary(msu):
        binaries.append(msu)

    # Python binaries and libs
    pylib = os.path.join(python_payload, PY_CUR, "lib")
    pybin = os.path.join(python_payload, PY_CUR, "bin")
    for pydir in [pylib, pybin]:
        if os.path.exists(pydir):
            for f in os.listdir(pydir):
                full_path = os.path.join(pydir, f)
                if is_signable_bin(full_path) or is_signable_lib(full_path):
                    binaries.append(full_path)
            for root, dirs, files in os.walk(pydir):
                for file_ in files:
                    full_path = os.path.join(root, file_)
                    if is_signable_lib(full_path):
                        binaries.append(full_path)

    # Entitled binaries
    entitled_binaries = [
        os.path.join(python_payload, PY_CUR, "Resources/Python.app"),
        os.path.join(pybin, "python3"),
    ]

    # Sign all binaries
    for binary in binaries:
        if os.path.exists(binary):
            if verbose:
                print(f"  Signing {binary}...")
            sign_binary(
                signing_id,
                binary,
                deep=True,
                force=True,
                options=["runtime"],
            )

    for binary in entitled_binaries:
        if os.path.exists(binary):
            if verbose:
                print(f"  Signing {binary} with entitlements...")
            sign_binary(
                signing_id,
                binary,
                deep=True,
                force=True,
                options=["runtime"],
                entitlements=ent_file,
            )
    
    # Sign python framework
    py_fwkpath = os.path.join(python_payload, PY_FWK)
    if os.path.exists(py_fwkpath):
        if verbose:
            print(f"  Signing {py_fwkpath}...")
        sign_binary(signing_id, py_fwkpath, deep=True, force=True)

def get_current_user():
    """Get the current non-root username"""
    try:
        return os.environ['SUDO_USER']
    except KeyError:
        return getpass.getuser()

def sign_package_as_user(pkg_path, signing_id, user=None):
    """Sign the package as the specified user"""
    if not user:
        user = get_current_user()
    
    signed_pkg = pkg_path.replace('.pkg', '-signed.pkg')
    
    print(f"Signing package as user '{user}'...")
    
    cmd = f'sudo -u {user} productsign --sign "{signing_id}" "{pkg_path}" "{signed_pkg}"'
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Package signed successfully: {signed_pkg}")
            
            verify_cmd = f'sudo -u {user} pkgutil --check-signature "{signed_pkg}"'
            verify_result = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True)
            if verify_result.returncode == 0:
                print("Signature verified")
            else:
                print("Could not verify signature")
            
            return signed_pkg
        else:
            print(f"Signing failed: {result.stderr}")
            return None
    except Exception as e:
        print(f"Signing error: {e}")
        return None

def main():
    p = argparse.ArgumentParser(
        description="Rebrands Munki's Managed Software Center for Swift-based MSC (Munki 7+) - macOS 26 Compatible"
    )

    p.add_argument("-a", "--appname", required=True, help="Your desired app name for Managed Software Center")
    p.add_argument("-k", "--pkg", help="Prebuilt munkitools pkg to rebrand")
    p.add_argument("-i", "--icon-file", help="Optional icon file (1024x1024 PNG)")
    p.add_argument("--identifier", default="com.googlecode.munki", help="Package identifier prefix")
    p.add_argument("-o", "--output-file", help="Base name for customized pkg")
    p.add_argument("-s", "--sign-package", help="Sign package with Developer ID Installer")
    p.add_argument("-S", "--sign-binaries", help="Sign binaries with Developer ID Application") 
    p.add_argument("-u", "--user", help="Username to use for signing (default: current sudo user)")
    p.add_argument("-v", "--verbose", action="store_true", help="Be more verbose")
    p.add_argument("-x", "--version", action="store_true", help="Print version and exit")
    p.add_argument("--debug", action="store_true", help="Print debug information")
    p.add_argument("--beta", action="store_true", help="Use the latest beta version instead of stable")
    
    args = p.parse_args()

    if args.version:
        print(VERSION)
        sys.exit(0)

    if os.geteuid() != 0:
        print("This script must be run as root for package operations!")
        print("Run with: sudo ./munki_rebrand_swift.py [options]")
        sys.exit(1)

    global verbose
    verbose = args.verbose or args.debug
    
    sign_user = args.user or get_current_user()
    print(f"Will sign packages as user: {sign_user}")

    outfilename = args.output_file or "munkitools"

    # Look for actool
    actool = next((x for x in ACTOOL if os.path.isfile(x)), None)
    if not actool:
        print(
            "WARNING: actool not found. Icon file will not be replaced in "
            "Assets.car format, which is required for macOS 26+."
        )

    # Process icon file if provided
    global icns, car
    if args.icon_file and os.path.isfile(args.icon_file):
        if icon_test(args.icon_file):
            print("Converting .png file to .icns and Assets.car...")
            try:
                icns, car = convert_to_icns_and_car(args.icon_file, tmp_dir, actool=actool)
                
                if car and os.path.isfile(car):
                    car_size = os.path.getsize(car)
                    print(f"  Generated Assets.car size: {car_size} bytes")
                    if car_size < 100000:  # Less than 100KB
                        print(f"  WARNING: Generated Assets.car is very small. Icon may not display correctly.")
                else:
                    print(f"  WARNING: Could not generate Assets.car. Icon may not display on macOS 26+.")
            except Exception as e:
                print(f"  ERROR generating icons: {e}")
                print("  Continuing without icon replacement...")
                icns = None
                car = None
        else:
            print("ERROR: icon file must be a 1024x1024 .png")
            sys.exit(1)

    # Download or use provided package
    output = os.path.join(tmp_dir, "munkitools.pkg")
    if not args.pkg:
        download_pkg(get_latest_munki_url(beta=args.beta), output)
        args.pkg = output
    elif args.pkg.startswith("http"):
        download_pkg(args.pkg, output)
        args.pkg = output

    if not os.path.isfile(args.pkg):
        print(f"Could not find munkitools pkg {args.pkg}")
        sys.exit(1)

    # Process package
    root_dir = os.path.join(tmp_dir, "root")
    expand_pkg(args.pkg, root_dir)

    # Debug: Show package structure
    if args.debug:
        print("\nPackage structure:")
        for item in os.listdir(root_dir):
            item_path = os.path.join(root_dir, item)
            if os.path.isdir(item_path):
                size = get_dir_size(item_path)
                print(f"  {item}/ - {size / (1024*1024):.2f} MB")

    # Get the actual version from the package
    munki_version = get_version_from_package(root_dir)
    print(f"Detected Munki version: {munki_version}")

    # Process apps
    print(f"Rebranding Managed Software Center to {args.appname}...")
    
    apps_processed = 0
    for item in os.listdir(root_dir):
        item_path = os.path.join(root_dir, item)
        if os.path.isdir(item_path) and item.startswith("munkitools_app"):
            if verbose:
                print(f"Processing package: {item}")
            
            processed = process_apps_for_macos26(item_path, args.appname, args.icon_file, args.sign_binaries, actool)
            apps_processed += processed

    if apps_processed == 0:
        print("No apps were processed!")
        sys.exit(1)

    # Update Distribution file
    distfile = os.path.join(root_dir, "Distribution")
    if os.path.exists(distfile):
        with open(distfile, 'r') as f:
            dist_content = f.read()
        
        dist_content = dist_content.replace("Managed Software Center", args.appname)
        
        with open(distfile, 'w') as f:
            f.write(dist_content)

    # Sign binaries if requested
    if args.sign_binaries:
        sign_all_binaries(args.sign_binaries, root_dir, args.appname)

    # Rebuild package
    final_pkg = f"{outfilename}-{munki_version}.pkg"
    flatten_pkg(root_dir, final_pkg)

    signed_pkg = final_pkg
    if args.sign_package:
        signed_pkg = sign_package_as_user(final_pkg, args.sign_package, sign_user)
        if not signed_pkg:
            print("Package signing failed, using unsigned package")
            signed_pkg = final_pkg

    print("")
    print(f"Successfully created: {signed_pkg}")
    print(f"App renamed to: {args.appname}.app")
    print(f"Bundle identifier updated for macOS 26 compatibility")
    
    # Get size of final package
    if os.path.exists(signed_pkg):
        pkg_size = os.path.getsize(signed_pkg)
        print(f"Final package size: {pkg_size / (1024*1024):.2f} MB")
    
    print("")
    if args.sign_package:
        print(f"Package signed with: {args.sign_package}")
    if args.sign_binaries:
        print(f"Binaries signed with: {args.sign_binaries}")
    if icns:
        print(f"Custom icon applied")
        if car and os.path.isfile(car):
            print(f"  - Assets.car generated: {os.path.getsize(car)} bytes")
        else:
            print(f"  - WARNING: Assets.car not generated. Icon may not display on macOS 26+")

if __name__ == "__main__":
    main()
