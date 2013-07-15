Reuqires:

fedmsg-relay
fedmsg-hub
datanommer
python-boto

------------------------------------

These files must be edited and put into the proper places in order for
them to work.

__init__.py replaces /usr/lib/python2.7/site-packages/datanommer/consumer/__init__.py

ssl.py and base.py replace their respective files in /etc/fedmsg.d/
(Base.py is currently set to prod)

SSL certs go into /etc/pki/fedmsg/ where they will be found by fedmsg
(Untested)

fedora_ec2.py and uploader.py stick together. They must be put into a place they
can be imported by __init__.py, the same file location as __init__ is fine.

boto.cfg must be put into either  /etc/boto.cfg (system wide) or into ~/.boto
(user-specific) and must be edited with the two access keys.

-----------------------------------

setup.sh does all of the above. Just run it once. Make sure all of the
packages are installed and you are running as root. The script will check
this.

-----------------------------------

TODO:
- Get Images from Koji (API?)
- Get Credentials and locations to upload images
- Edit __init__ with above information
- Make ssl certs (and make sure it actually works)

- (Optional?) Update 'upload-fedora' package to replace the upload scripts
