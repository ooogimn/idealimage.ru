
import os
import django
from django.conf import settings

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IdealImage_PDJ.settings')
django.setup()

from Home.models import Portal

def fix_portal_paths():
    portals = Portal.objects.all()
    count = 0
    for p in portals:
        original_path = p.image.name
        if not original_path:
            continue
            
        # Get only the filename
        filename = os.path.basename(original_path)
        
        # We want the path to be 'landing/portals/filename'
        # Django's FileField expects the name relative to MEDIA_ROOT
        # In our model, upload_to is 'landing/portals/'
        
        print(f"Fixing {p.name}: {original_path} -> landing/portals/{filename}")
        p.image.name = f"landing/portals/{filename}"
        p.save()
        count += 1
        
    print(f"Done. Fixed {count} portals.")

if __name__ == "__main__":
    fix_portal_paths()
