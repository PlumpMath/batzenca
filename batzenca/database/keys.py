from base import Base, EntryNotFound
from sqlalchemy import Column, Integer, String, Date, ForeignKey
from sqlalchemy.ext.associationproxy import association_proxy

import datetime
import warnings

class Key(Base):
    """
    """

    __tablename__ = 'keys'

    id        = Column(Integer, primary_key=True)           # database id
    kid       = Column(String, nullable=False, unique=True) # 8 byte pgp key id of the form 0x0123456789abcdef
    name      = Column(String)                              # user id
    email     = Column(String)                              # email as stored in key
    timestamp = Column(Date)                                # date it was added to the database
    peer_id   = Column(Integer, ForeignKey("peers.id"))     # points to the peer this key belongs to

    releases    = association_proxy('release_associations', 'release')
    
    def __init__(self, kid, name=None, email=None, timestamp=None):
        self.kid = "0x%016x"%kid

        from batzenca.session import session
        if not session.gnupg.key_exists(self.kid):
            if name is None or email is None or timestamp is None:
                raise ValueError("The key %s does not exist in GnuPG and not enough information was provided for generating Key instance without it."%self.kid)
            self.name      = unicode(name.strip())
            self.email     = str(email.strip())
            self.timestamp = timestamp
            return

        uid = session.gnupg.key_uid(self.kid)

        self.name = uid.name
        self.email = str(uid.email)
        self.timestamp = session.gnupg.key_timestamp(self.kid)

    @classmethod
    def from_keyid(cls, kid):
        """
        Query the database for key id kid.

        INPUT:

        - ``kid`` - key id as integer or string in hexadecimal format
        """
        try:
            kid = "0x%016x"%kid
        except TypeError:
            pass
        from batzenca.session import session
        res = session.db_session.query(cls).filter(cls.kid == kid)

        if res.count() == 0:
            raise EntryNotFound("No key with key id '%s' in database."%kid)
        else:
            if res.count() > 1:
                raise RuntimeError("More than one key with key id '%s' in database."%kid)
            return res.first()

    @classmethod
    def from_name(cls, name):
        """
        .. note::

           The returned object was queried from the main session and lives there.
        """
        from batzenca.session import session
        res = session.db_session.query(cls).filter(cls.name == name)

        if res.count() == 0:
            raise ValueError("No key with name '%s' in database."%name)
        else:
            if res.count() > 1:
                warnings.warn("More than one key with name '%s' found, picking first one."%name)
            return res.first()

    @classmethod
    def from_email(cls, email):
        """
        .. note::

           The returned object was queried from the main session and lives there.
        """
        from batzenca.session import session
        res = session.db_session.query(cls).filter(cls.email == email)

        if res.count() == 0:
            raise EntryNotFound("No key with email '%s' in database."%email)
        else:
            if res.count() > 1:
                warnings.warn("More than one key with email '%s' found, picking first one."%email)
            return res.first()

    @classmethod
    def from_filename(cls, filename):
        """
        .. note::

           The returned object was not added to any session, any keys found in ``filename`` were
           added to the GnuPG database.
        """
        from batzenca.session import session

        with open(filename) as fh:
            data = fh.read()
            res = session.gnupg.keys_import(data)
            if len(res) == 0:
                raise EntryNotFound("No key found in in file '%s'"%filename)
            else:
                if len(res) > 1:
                    warnings.warn("More than one key found in file '%s', picking first one.\n"%filename)
                fpr = res.keys()[0]
                return cls(int("0x"+fpr[-16:],16))

    @classmethod
    def from_str(cls, ascii_data):
        """
           .. note::
        
           The returned object was not added to any session, any keys found in ``ascii_data`` were
           added to the GnuPG database.
        """
        from batzenca.session import session
        res = session.gnupg.keys_import(ascii_data)
        if len(res) == 0:
            cut = "\n".join(ascii_data.splitlines()[:20])
            raise EntryNotFound("""No key found in in provided string\n\n%s"""%cut)
        else:
            cut = "\n".join(ascii_data.splitlines()[:20])
            if len(res) > 1:
                warnings.warn("""More than one key found in string, picking first one\n\n%s"""%cut)
            fpr = res.keys()[0]
            return cls(int("0x"+fpr[-16:],16))
        
    def __nonzero__(self):
        from batzenca.session import session
        return session.gnupg.key_okay(self.kid)

    def is_expired(self):
        from batzenca.session import session
        return session.gnupg.key_expired(self.kid)

    def __str__(self):
        return u"%s: %s <%s>"%(self.kid,self.name,self.email)

    def __repr__(self):
        return "<Key: %s>"%(self.kid)

    def __len__(self):
        from batzenca.session import session
        return session.gnupg.key_min_len(self.kid)

    def expires(self):
        from batzenca.session import session
        return session.gnupg.key_expires(self.kid)

    def __lt__(self, other):
        return self.timestamp < other.timestamp

    def __hash__(self):
        return int(self.kid, 16)

    @property
    def algorithms(self):
        from batzenca.session import session
        return session.gnupg.key_pubkey_algos(self.kid)

    def is_signed_by(self, signer):
        from batzenca.session import session
        return session.gnupg.key_any_uid_is_signed_by(self.kid, signer.kid)

    def sign(self, signer):
        from batzenca.session import session
        session.gnupg.key_sign(self.kid, signer.kid)

    def revoke_signature(self, signer, reason=""):
        from batzenca.session import session
        session.gnupg.key_revsig(self.kid, signer.kid, 4, msg=reason)

    def is_valid(self):
        # TODO: key_validity > ?
        return bool(self) and gnupg.key_validity(self.kid) > 0

    def hard_delete(self):
        raise NotImplementedError

    def _edit(self):
        """
        .. warning:

           This will open an interactive session using rawinput
        """
        from batzenca.session import session
        return session.gnupg.key_edit(self.kid)

    def delete_signature(self, signer):
        """
        .. warning:

           This will open an interactive session using rawinput
        """
        from batzenca.session import session
        try:
            return session.gnupg.key_delete_signature(self.kid, signer.kid)
        except AttributeError:
            return session.gnupg.key_delete_signature(self.kid, signer)

    def signatures(self):
        from batzenca.session import session
        keyids = tuple("0x"+keyid for keyid in session.gnupg.key_signatures(self.kid))
        sigs = []
        for keyid in keyids:
            if int(self.kid, 16) == int(keyid,16):
                sigs.append(self)
                continue
            try:
                sigs.append(Key.from_keyid(int(keyid,16)))
            except EntryNotFound:
                sigs.append(keyid)
        return sigs
        
    @property
    def _gnupg_key(self):
        from batzenca.session import session
        return session.gnupg.key_get(self.kid)