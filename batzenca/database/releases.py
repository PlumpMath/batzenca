import datetime

import warnings

import sqlalchemy
from sqlalchemy import Column, Integer, String, Date, Boolean, ForeignKey
from sqlalchemy.orm import relationship, backref, Session
from sqlalchemy.ext.associationproxy import association_proxy

from base import Base, EntryNotFound
from peers import Peer
from keys import Key

class ReleaseKeyAssociation(Base):
    """
    """

    __tablename__ = 'releasekeyassociations'

    left_id          = Column(Integer, ForeignKey('keys.id'),     primary_key=True)
    right_id         = Column(Integer, ForeignKey('releases.id'), primary_key=True)
    policy_exception = Column(Boolean)
    is_active        = Column(Boolean)

    key              = relationship("Key", backref=backref("release_associations", cascade="all, delete-orphan") )
    release          = relationship("Release", backref=backref("key_associations", cascade="all, delete-orphan") )

    def __init__(self, key, active=True, policy_exception=False):
        self.key = key
        self.is_active = active
        self.policy_exception = policy_exception

class Release(Base):
    """
    """

    __tablename__ = 'releases'

    id             = Column(Integer, primary_key=True)
    mailinglist_id = Column(Integer, ForeignKey('mailinglists.id'))
    mailinglist    = relationship("MailingList", backref=backref("releases", order_by="Release.date", cascade="all, delete-orphan"))
    date           = Column(Date)

    policy_id      = Column(Integer, ForeignKey('policies.id'))
    policy         = relationship("Policy")

    keys           = association_proxy('key_associations', 'key')

    def __init__(self, mailinglist, date, active_keys, inactive_keys=None, policy=None):
        self.mailinglist = mailinglist

        if date is None:
            date = datetime.date.today()
        self.date = date

        if policy is not None:
            self.policy = policy
        else:
            self.policy = mailinglist.policy

        for key in active_keys:
            self.key_associations.append(ReleaseKeyAssociation(key=key))

        for key in inactive_keys:
            self.key_associations.append(ReleaseKeyAssociation(key=key, active=False))

    @classmethod
    def from_mailinglist_and_date(cls, mailinglist, date):
        from batzenca.session import session
        res = session.db_session.query(cls).filter(cls.mailinglist_id == mailinglist.id, cls.date == date)

        if res.count() == 0:
            raise EntryNotFound("No release for mailinglist '%s' with date '%s' in database."%(mailinglist, date))
        else:
            if res.count() > 1:
                warnings.warn("More than one release for mailinglist '%s' with date '%s' in database, picking first one"%(mailinglist, date))
            return res.first()

    def inherit(self, date=None, policy=None, deactivate_invalid=True, delete_old_inactive_keys=True):
        active_keys   = list(self.active_keys)
        inactive_keys = list(self.inactive_keys)

        if policy is None:
            policy = self.policy
            
        release = Release(mailinglist=self.mailinglist, 
                          date=date, 
                          active_keys = active_keys, 
                          inactive_keys = inactive_keys, 
                          policy=policy)

        if deactivate_invalid:
            release.deactivate_invalid() 
        if delete_old_inactive_keys:
            release.delete_old_inactive_keys(delete_old_inactive_keys)
            
        for key in self.active_keys:
            if self.has_exception(key):
                release.add_exception(key)

        return release

    def verify(self, ignore_exceptions=False):
        for assoc in self.key_associations:
            if assoc.is_active and (ignore_exceptions or not assoc.policy_exception):
                self.policy.check(assoc.key)
    def __repr__(self):
        s = "<Release: %s, %s, %s (%s + %s) keys>"%(self.id, self.date, len(self.key_associations), len(self.active_keys), len(self.inactive_keys))
        return unicode(s).encode('utf-8')
                
    def __str__(self):
        from batzenca.database.policies import PolicyViolation
        inact_no_sig = 0
        inact_expired = 0
        policy = self.policy
        for key in self.keys:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", PolicyViolation)
                if policy.check_ca_signature(key) == False:
                    inact_no_sig += 1
                    continue

            if key.expires() and key.expires() < self.date:
                inact_expired += 1
                continue

        return "date: %10s, list: %10s, policy date: %10s, active keys: %3d, inactive keys: %2d (expired: %2d, not signed: %2d), total keys: %3d"%(self.date, self.mailinglist.name, self.policy.implementation_date,
                                                                                                                                                   len(self.active_keys), len(self.inactive_keys), inact_expired, inact_no_sig, len(self.keys))

    def print_active_keys(self):
        for key in sorted(self.active_keys):
            print key

    def dump_keys(self):
        from batzenca.session import session
        data = session.gnupg.keys_export(self.keys)
        return data.read()

    def diff(self, other):
        keys_prev = set(other.active_keys + self.inactive_keys)        
        keys_curr = set(self.active_keys) # keys that are in this release

        # keys that used to be in but are not any more
        keys_out = keys_prev.difference(keys_curr)
        # keys that are new
        keys_in  = keys_curr.difference(keys_prev)

        
        peers_prev = set([Peer.from_key(key) for key in other.active_keys])
        peers_curr = set([Peer.from_key(key) for key in keys_curr])
        peers_in   = set([Peer.from_key(key) for key in keys_in  ])
        peers_out  = set([Peer.from_key(key) for key in keys_out ])

        peers_joined  = peers_curr.difference(peers_prev)
        peers_changed = peers_in.intersection(peers_out)
        peers_left    = peers_prev.difference(peers_curr)


        return keys_in, keys_out, peers_joined, peers_changed, peers_left

    @property
    def peers(self):
        return tuple(Peer.from_key(key) for key in sorted(self.active_keys, key=lambda x: x.name.lower()))

    @staticmethod
    def _format_entry(i, key):
            return (u"  %3d. %s"%(i, key), u"       %s"%key.peer)
        
        
    def publish(self, previous=None, check=True, testrun=False):

        if not testrun:
            self.date = datetime.date.today()
        
        keys = []

        if check:
            self.verify()

        for i,key in enumerate(sorted(self.active_keys, key=lambda x: x.name.lower())):
            keys.extend(Release._format_entry(i, key))
        keys = "\n".join(keys)

        if previous is None:
            previous = self.prev

        if previous:
            keys_in, keys_out, peers_joined, peers_changed, peers_left = self.diff(previous)

            keys_in  = "\n".join(sum([self._format_entry(i, key) for i,key in enumerate(keys_in)],  tuple()))
            keys_out = "\n".join(sum([self._format_entry(i, key) for i,key in enumerate(keys_out)], tuple()))

            peers_joined  = ", ".join(peer.name for peer in peers_joined)
            peers_changed = ", ".join(peer.name for peer in peers_changed)
            peers_left    = ", ".join(peer.name for peer in peers_left)
        else:
            keys_in, keys_out, peers_joined, peers_changed, peers_left = "","","","",""
        msg = self.mailinglist.key_update_msg.format(mailinglist=self.mailinglist.name, keys=keys,
                                                     keys_in       = keys_in,
                                                     keys_out      = keys_out,
                                                     peers_in      = peers_joined,
                                                     peers_changed = peers_changed,
                                                     peers_out     = peers_left)
        from batzenca.session import session
        keys = session.gnupg.keys_export( [key.kid for key in self.keys] )

        return msg, keys

    @property
    def active_keys(self):
        if self.id is None:
            return [assoc for assoc in self.key_associations if assoc.is_active]
        from batzenca.session import session
        return session.db_session.query(Key).join(ReleaseKeyAssociation).filter(ReleaseKeyAssociation.right_id == self.id, ReleaseKeyAssociation.is_active == True).all()

    @property
    def inactive_keys(self):
        if self.id is None:
            return [assoc.key for assoc in self.key_associations if not assoc.is_active]
        from batzenca.session import session
        return session.db_session.query(Key).join(ReleaseKeyAssociation).filter(ReleaseKeyAssociation.right_id == self.id, ReleaseKeyAssociation.is_active == False).all()

    def deactivate_invalid(self):
        for assoc in self.key_associations:
            if assoc.is_active:
                if not bool(assoc.key):
                    assoc.is_active = False
                elif not assoc.key.is_signed_by(self.policy.ca):
                    assoc.is_active = False

    def delete_old_inactive_keys(self, releasecount=True):
        if not releasecount:
            return

        if releasecount is True:
            releasecount = 5

        old_release = self
        for i in range(releasecount):
            old_release = old_release.prev

        delete_keys = []
        for key in self.inactive_keys:
            if key not in old_release.active_keys:
                delete_keys.append(key)
        for key in delete_keys:
            assoc = self._get_assoc(key)
            self.key_associations.remove(assoc)
            from batzenca.session import session
            session.db_session.delete(assoc)
            
                
    def _get_assoc(self, key):
        if key.id is None or self.id is None:
            for assoc in self.key_associations:
                if assoc.key is key and assoc.release is self:
                    return assoc
            raise ValueError("Key '%s' is not in release '%s'"%(key, self))

        from batzenca.session import session
        res = session.db_session.query(ReleaseKeyAssociation).filter(ReleaseKeyAssociation.left_id == key.id, ReleaseKeyAssociation.right_id == self.id)
        if res.count() > 1:
            raise RuntimeError("The key '%s' is associated with the release '%' more than once; the database is in an inconsistent state."%(key, self))
        if res.count() == 0:
            raise ValueError("Key '%s' is not in release '%s'"%(key, self))
        return res.first()

    def add_exception(self, key):
        assoc = self._get_assoc(key)
        assoc.policy_exception = True

    def has_exception(self, key):
        assoc = self._get_assoc(key)
        return assoc.policy_exception

    def is_active(self, key):
        assoc = self._get_assoc(Key)
        return assoc.is_active

    def update_key_from_peer(self, peer):
        raise NotImplementedError

    def add_key(self, key, active=True, check=True):
        # TODO check if peer is already in release
        if key.peer is None:
            raise ValueError("Key '%s' has no peer associated"%key)
        else:
            if active and key.peer in self:
                raise ValueError("Peer '%s' associated with Key '%s' already has an active key in this release"%(key.peer, key))
            
        if check and active:
            self.policy.check(key)
            
            
        self.key_associations.append(ReleaseKeyAssociation(key=key, active=active))

    def __contains__(self, obj):
        from batzenca.session import session

        if self.id is None:
            raise RuntimeError("The object '%s' was not committed to the database yet, we cannot issue queries involving its id yet."%self)

        try:
            if obj.id is None:
                raise RuntimeError("The object '%s' was not committed to the database yet, we cannot issue queries involving its id yet."%obj)
        except AttributeError:
            raise TypeError("Cannot handle objects of type '%s'"%type(obj))

        if isinstance(obj, Key):
            res = session.db_session.query(Key).join(ReleaseKeyAssociation).filter(ReleaseKeyAssociation.left_id == obj.id, ReleaseKeyAssociation.right_id == self.id, ReleaseKeyAssociation.is_active == True)
            if res.count() == 0:
                return False
            elif res.count() == 1:
                return True
            else:
                raise RuntimeError("The key '%s' is associated with the release '%' more than once; the database is in an inconsistent state."%(obj, self))
            
        elif isinstance(obj, Peer):
            res = session.db_session.query(Peer).join(Key).join(ReleaseKeyAssociation).filter(Key.peer_id == obj.id, ReleaseKeyAssociation.left_id == Key.id, ReleaseKeyAssociation.right_id == self.id, ReleaseKeyAssociation.is_active == True)
            if res.count() == 0:
                return False
            elif res.count() == 1:
                return True
            else:
                raise RuntimeError("The peer '%s' is associated with the release '%' more than once; the database is in an inconsistent state."%(obj, self))
        else:
            raise TypeError("Cannot handle objects of type '%s'"%type(obj))

    @property
    def prev(self):
        idx = self.mailinglist.releases.index(self)
        if idx > 0:
            return self.mailinglist.releases[idx-1]
        else:
            return None

    def csv(self):
        raise NotImplementedError