"""
Based on https://pypi.python.org/pypi/pgp-mime/
"""
from email import Message
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.encoders import encode_7or8bit
from email import encoders
from email.mime.base import MIMEBase
import email

import os
import mimetypes

from batzenca.session import session


class PGPMIMEsigned(MIMEMultipart):
    def __init__(self, msg=None, signer=None):
        if msg is None:
            return
        if msg.is_multipart():
            # we need these to get our message correctly parsed by KMail and Thunderbird
            msg.preamble = 'This is a multi-part message in MIME format.'
            msg.epilogue = '' 

        if signer is not None:
            msg_str = flatten(msg)
            sig     = session.gnupg.msg_sign(msg_str, signer.kid)
            sig = MIMEApplication(_data=sig,
                                  _subtype='pgp-signature; name="signature.asc"',
                                  _encoder=encode_7or8bit)
            sig['Content-Description'] = 'This is a digital signature.'
            sig.set_charset('us-ascii')

            MIMEMultipart.__init__(self, 'signed', micalg='pgp-sha1', protocol='application/pgp-signature')
            self.attach(msg)
            self.attach(sig)
            
    @classmethod
    def from_parts(cls, msg, sig):
        self = PGPMIMEsigned()
        MIMEMultipart.__init__(self, 'signed', micalg='pgp-sha1', protocol='application/pgp-signature')
        self.attach(msg)
        self.attach(sig)
        return self
            
    def signatures(self):
        subparts = self.get_payload()
        assert(len(subparts) == 2)
        msg, sig = subparts
        msg_str = flatten(msg)
        res = session.gnupg.sig_verify(msg_str, sig.get_payload())
        return res

    def is_signed_by(self, signer):
        from batzenca import EntryNotFound, Key

        signatures = self.signatures()
            
        for sig in signatures:
            if isinstance(signer, Key):
                try:
                    key = Key.from_keyid(int(sig[-16:],16))
                    if key == signer:
                        return True
                except EntryNotFound:
                    pass
            else:
                try:
                    key = Key.from_keyid(sig)
                    if key.email == signer:
                        return True
                except EntryNotFound:
                    pass
        return False
        
class PGPMIMEencrypted(MIMEMultipart):
    def __init__(self, msg, recipients):

        MIMEMultipart.__init__(self, 'encrypted', micalg='pgp-sha1', protocol='application/pgp-encrypted')

        body = flatten(msg)
        encrypted = session.gnupg.msg_encrypt(body, [r.kid for r in recipients])

        payload = MIMEApplication(_data=encrypted,
                                  _subtype='octet-stream',
                                  _encoder=encode_7or8bit)
        payload['Content-Disposition'] = 'inline; name="encrypted.asc"'
        payload.set_charset('us-ascii')

        control = MIMEApplication(_data='Version: 1\n',
                                  _subtype='pgp-encrypted',
                                  _encoder=encode_7or8bit)
        control.set_charset('us-ascii')
        
        self.attach(control)
        self.attach(payload)
        self['Content-Disposition'] = 'attachment'

    def decrypt(self):
        subparts = self.get_payload()
        assert(len(subparts) == 2)
        control, payload = subparts

        payload = payload.get_payload()
        raw = session.gnupg.msg_decrypt(payload)
        msg = email.message_from_string(raw)

        if msg.is_multipart():
            subparts = msg.get_payload()
            if len(subparts) == 2:
                msg, sig = subparts
                if "pgp-signature" in sig.get_content_subtype():
                    return PGPMIMEsigned.from_parts(msg, sig)
        return msg
        
def PGPMIME(msg, recipients, signer):
    return PGPMIMEencrypted( PGPMIMEsigned(msg, signer), recipients)

def flatten(msg):
    from cStringIO import StringIO
    from email.generator import Generator
    fp = StringIO()
    g = Generator(fp, mangle_from_=False)
    g.flatten(msg)
    text = fp.getvalue()

    return '\r\n'.join(text.splitlines()) + '\r\n'
