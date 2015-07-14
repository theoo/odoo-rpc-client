from openerp_proxy.utils import wpartial
from openerp_proxy.utils import ustr
from openerp_proxy.orm.object import Object
from openerp_proxy.orm.cache import empty_cache
from extend_me import ExtensibleType

import collections
import abc


__all__ = (
    'Record',
    'RecordRelations',
    'ObjectRecords',
    'RecordList',
    'empty_cache',
)


RecordMeta = ExtensibleType._('Record')


def get_record(obj, rid, cache=None, context=None):
    """ Creates new Record instance

        Use this method to create new records, because of standard
        object creation bypasses extension's magic.

            :param obj: instance of Object this record is related to
            :param int rid: ID of database record to fetch data from
            :param cache: dictionary of structure {object.name: {object_id: data} }
            :type cache: defaultdict(lambda: defaultdict(dict))
            :param dict context: if specified, then cache's context will be updated
            :return: created Record instance
            :rtype: Record instance
    """
    return RecordMeta.get_object(obj, rid, cache=cache, context=context)


class Record(object):
    """ Base class for all Records

        Constructor
            :param obj: instance of object this record is related to
            :param int rid: ID of database record to fetch data from
            :param cache: dictionary of structure {object.name: {object_id: data} }
            :type cache: defaultdict(lambda: defaultdict(dict))
            :param dict context: if specified, then cache's context will be updated

        Note, to create instance of cache call *empty_cache*
    """

    __metaclass__ = RecordMeta
    __slots__ = ['__dict__', '_object', '_cache', '_lcache', '_id']

    def __init__(self, obj, rid, cache=None, context=None):
        assert isinstance(obj, Object), "obj should be Object"
        assert isinstance(rid, (int, long)), "rid must be int"

        self._id = rid
        self._object = obj
        self._cache = empty_cache(obj.proxy) if cache is None else cache
        self._lcache = self._cache[obj.name]
        if context is not None:
            self._lcache.update_context(context)

    def __dir__(self):
        # TODO: expose also object's methods
        res = dir(super(Record, self))
        res.extend(self._columns_info.keys())
        res.extend(['read', 'search', 'write', 'unlink'])
        return res

    @property
    def id(self):
        """ Record ID
        """
        return self._id

    @property
    def _data(self):
        """ Data dictionary for this record.
            (Just a proxy to cache)
        """
        return self._lcache[self._id]

    @property
    def context(self):
        """ Returns context to be used for thist record
        """
        return self._lcache.context

    @property
    def _service(self):
        """ Returns instance of related Object service instance
        """
        return self._object.service

    @property
    def _proxy(self):
        """ Returns instance of related Client object
        """
        return self._object.proxy

    @property
    def _columns_info(self):
        """ Returns dictionary with information about columns of related object
        """
        return self._object.columns_info

    @property
    def as_dict(self):
        """ Provides dictionary with record's data in raw form
        """
        return self._data.copy()

    @property
    def _name(self):
        """ Returns result of name_get for this record
        """
        if self._data.get('__name_get_result', None) is None:
            lcache = self._lcache
            data = self._object.name_get(lcache.keys(), context=self.context)
            for _id, name in data:
                lcache[_id]['__name_get_result'] = name
        return self._data.get('__name_get_result', 'ERROR')

    def __unicode__(self):
        return u"R(%s, %s)[%s]" % (self._object.name, self.id, ustr(self._name))

    def __str__(self):
        return unicode(self).encode('utf-8')

    def __repr__(self):
        return str(self)

    def __int__(self):
        return self._id

    def __hash__(self):
        return hash((self._object.name, self._id))

    def __eq__(self, other):
        if isinstance(other, Record):
            return other.id == self._id

        if isinstance(other, (int, long)):
            return self._id == other

        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def _get_field(self, ftype, name):
        """ Returns value for field 'name' of type 'type'

            :param str ftype: type of field to det value for
            :param str name: name of field to read

            Should be overridden by extensions to provide better hadling for diferent field values
        """
        if name not in self._data:
            lcache = self._lcache
            read_data = self._object.read(lcache.get_ids_to_read(name), [name], context=self.context)
            for data in read_data:
                lcache.cache_field(data['id'], ftype, name, data[name])

        return self._data[name]

    # Allow dictionary access to data fields
    def __getitem__(self, name):
        if name == 'id':
            return self.id

        field = self._columns_info.get(name, None)

        if field is None:
            raise KeyError("No such field %s in object %s, %s" % (name, self._object.name, self.id))

        ftype = field and field['type']

        # TODO: refactore to be able to pass field instead of only field type
        return self._get_field(ftype, name)

    # Allow to access data as attributes and call object's methods
    # directly from record object
    def __getattr__(self, name):
        try:
            res = self[name]   # Try to get data field
        except KeyError:
            method = getattr(self._object, name)
            res = wpartial(method, [self.id])
            setattr(self, name, res)
        return res

    def refresh(self):
        """Reread data and clean-up the caches

           :returns: self
           :rtype: instance of Record
        """
        self._data.clear()
        self._data['id'] = self._id
        return self

    def read(self, fields=None, context=None, multi=False):
        """ Rereads data for this record (or for al records in whole cache)

            :param list fields: list of fields to be read (optional)
            :param dict context: context to be passed to read (optional)
                                 does not midify record's context
            :param bool multi: if set to True, that data will be read for
                               all records of this object in current
                               cache (query).
            :return: dict with data had been read
            :rtype: dict
        """
        ctx = {} if self.context is None else self.context.copy()
        args = [self._lcache.keys()] if multi else [[self.id]]

        kwargs = {}

        if fields is not None:
            args.append(fields)

        if ctx:
            kwargs['context'] = ctx

        res = {}
        for rdata in self._object.read(*args, **kwargs):
            self._lcache[rdata['id']].update(rdata)
            if rdata['id'] == self.id:
                res = rdata
        return res


RecordListMeta = ExtensibleType._('RecordList', with_meta=abc.ABCMeta)


def get_record_list(obj, ids=None, fields=None, cache=None, context=None):
    """ Returns new instance of RecordList object.

        :param obj: instance of Object to make this list related to
        :type obj: Object instance
        :param ids: list of IDs of objects to read data from
        :type ids: list of int
        :param fields: list of field names to read by default  (not used now)
        :type fields: list of strings (not used now)
        :param cache: dictionary of structure {object.name: {object_id: data} }
        :type cache: defaultdict(lambda: defaultdict(dict))
        :param context: context to be passed automatocally to methods called from this list (not used yet)
        :type context: dict
    """
    return RecordListMeta.get_object(obj, ids, fields=fields, cache=cache, context=context)


class RecordList(collections.MutableSequence):
    """Class to hold list of records with some extra functionality

        :param obj: instance of Object to make this list related to
        :type obj: Object instance
        :param ids: list of IDs of objects to read data from
        :type ids: list of int
        :param fields: list of field names to read by default
        :type fields: list of strings
        :param cache: dictionary of structure {object.name: {object_id: data} }
        :type cache: defaultdict(lambda: defaultdict(dict))
        :param context: context to be passed automatocally to methods called from this list (not used yet)
        :type context: dict

    """
    __metaclass__ = RecordListMeta

    __slots__ = ('_object', '_cache', '_lcache', '_records')

    # TODO: expose object's methods via implementation of __dir__

    def __init__(self, obj, ids=None, fields=None, cache=None, context=None):
        """
        """
        self._object = obj
        self._cache = _cache = empty_cache(obj.proxy) if cache is None else cache
        self._lcache = self._cache[obj.name]

        if context is not None:
            self._lcache.update_context(context)

        ids = [] if ids is None else ids

        self._lcache.update_keys(ids)

        self._records = [get_record(obj, id_, cache=_cache)
                         for id_ in ids]

        # if there some fields prefetching was requested, do it
        if fields is not None:
            self.prefetch(*fields)

    @property
    def object(self):
        """ Object this record is related to
        """
        return self._object

    @property
    def context(self):
        """ Returns context to be used for this list
        """
        return self._lcache.context

    @property
    def ids(self):
        """ IDs of records present in this RecordList
        """
        return [r.id for r in self._records]

    @property
    def records(self):
        """ Returns list (class 'list') of records
        """
        return self._records

    @property
    def length(self):
        """ Returns length of this record list
        """
        return len(self._records)

    def _new_context(self, new_context=None):
        """ Create new context which is combination of self.context and passed context argument
            mostly for internal usage

            :param dict new_context: new context. default is None
            :return: new context dict which is combination of self.context and new_context or None
            :rtype: dict|None
        """
        if new_context is None:
            return self.context

        ctx = {} if self.context is None else self.context.copy()
        ctx.update(new_context)
        return ctx

    # Container related methods
    def __getitem__(self, index):
        if isinstance(index, slice):
            # Note no context passed, because it is stored in cache
            return get_record_list(self.object,
                                   ids=(r.id for r in self._records[index]),
                                   cache=self._cache)
        return self._records[index]

    def __setitem__(self, index, value):
        self._records[index] = value

    def __delitem__(self, index):
        del self._records[index]

    def __iter__(self):
        return iter(self._records)

    def __len__(self):
        return self.length

    def __contains__(self, item):
        if isinstance(item, (int, long)):
            return item in self.ids
        if isinstance(item, Record):
            return item in self._records
        return False

    def insert(self, index, item):
        """ Insert record to list

            :param item: Record instance to be inserted into list. if int or long passed, it considered to be ID of record
            :type item: Record|int|long
            :param int index: position where to place new element
            :return: self
            :rtype: RecordList
        """
        assert isinstance(item, (Record, int, long)), "Only Record or int or long instances could be added to list"
        if isinstance(item, Record):
            self._records.insert(index, item)
        else:
            self._records.insert(index, self._object.read_records(item))
        return self

    # Overridden to make ability to call methods of object on list of IDs
    # present in this RecordList
    def __getattr__(self, name):
        method = getattr(self.object, name)
        res = wpartial(method, self.ids, context=self.context)
        #setattr(self, name, res)  # commented because of __slots__
        return res

    def __str__(self):
        return "RecordList(%s): length=%s" % (self.object.name, self.length)
    __repr__ = __str__

    def refresh(self):
        """ Cleanup data caches. next try to get data will cause rereading of it

           :returns: self
           :rtype: instance of RecordList
        """
        for record in self.records:
            record.refresh()
        return self

    def sort(self, cmp=None, key=None, reverse=False):
        """ sort(cmp=None, key=None, reverse=False) -- inplace sort
            cmp(x, y) -> -1, 0, 1
        """
        return self._records.sort(cmp=cmp, key=key, reverse=reverse)

    def copy(self, context=None, new_cache=False):
        """ Returns copy of this list, possibly with modified context
            and new empty cache.

            :param dict context: new context values to be used on new list
            :param true new_cache: if set to True, then new cache
                                   instance will be created for copied list
            :return: copyt of this record list.
            :rtype: RecordList instance
        """
        cache = empty_cache(self.object.proxy) if new_cache else self._cache
        return get_record_list(self.object,
                               ids=self.ids,
                               cache=cache,
                               context=context)

    def existing(self, uniqify=True):
        """ Filters this list with only existing items

            :parm bool uniqify: if set to True, then all dublicates will be removed. Default: True
            :return: new RecordList instance
            :rtype: RecordList
        """
        existing_ids = self.exists()
        new_ids = []
        for id_ in self.ids:
            if id_ not in existing_ids:
                continue
            if uniqify and id_ in new_ids:
                continue
            new_ids.append(id_)
        return get_record_list(self.object,
                               ids=new_ids,
                               cache=self._cache)

    def prefetch(self, *fields):
        """ Prefetches specified fields into cache
            if no fields passed, then all 'simple_fields' will be prefetched

            By default field read performed only when that field is requested,
            thus when You need to read more then one field, few rpc requests
            will be performed. to avoid multiple unneccessary rpc calls this
            method is implemented.

            :return: self, which allows chaining of operations
            :rtype: RecordList
        """
        fields = fields if fields else self.object.simple_fields

        self._cache[self.object.name].prefetch_fields(fields)

        return self

    # remote method overrides
    def search(self, domain, *args, **kwargs):
        """ Performs normal search, but adds ``('id', 'in', self.ids)`` to search domain

            :returns: list of IDs found
            :rtype: list of integers
        """
        kwargs['context'] = self._new_context(kwargs.get('context', None))
        return self.object.search([('id', 'in', self.ids)] + domain, *args, **kwargs)

    def search_records(self, domain, *args, **kwargs):
        """ Performs normal search_records, but adds ``('id', 'in', seld.ids)`` to domain

            :returns: RecordList of records found
            :rtype: RecordList instance
        """
        kwargs['context'] = self._new_context(kwargs.get('context', None))
        return self.object.search_records([('id', 'in', self.ids)] + domain, *args, **kwargs)

    def read(self, fields=None, context=None):
        """ Read wrapper. Takes care about adding RecordList's context to
            object's read method
        """
        kwargs = {}
        args = []

        kwargs['context'] = self._new_context(kwargs.get('context', None))

        if fields is not None:
            args.append(fields)

        return self.object.read(self.ids, *args, **kwargs)


class RecordRelations(Record):
    """
        Adds ability to browse related fields from record::

            >>> o = client['sale.order.line'].read_records(1)
            >>> o.order_id
            R(sale.order, 25)[SO025]

    """

    def __init__(self, *args, **kwargs):
        super(RecordRelations, self).__init__(*args, **kwargs)
        self._related_objects = {}

    def _get_many2one_rel_obj(self, name, rel_data, cached=True):
        """ Method used to fetch related object by name of field that points to it
        """
        if name not in self._related_objects or not cached:
            if rel_data:
                # Do not forged about relations in form [id, name]
                rel_id = rel_data[0] if isinstance(rel_data, (list, tuple)) else rel_data

                rel_obj = self._service.get_obj(self._columns_info[name]['relation'])
                self._related_objects[name] = get_record(rel_obj, rel_id, cache=self._cache, context=self.context)
            else:
                self._related_objects[name] = False
        return self._related_objects[name]

    def _get_one2many_rel_obj(self, name, rel_ids, cached=True, limit=None):
        """ Method used to fetch related objects by name of field that points to them
            using one2many relation
        """
        if name not in self._related_objects or not cached:
            rel_obj = self._service.get_obj(self._columns_info[name]['relation'])
            self._related_objects[name] = get_record_list(rel_obj, rel_ids, cache=self._cache, context=self.context)
        return self._related_objects[name]

    # Overridden to allow browse for related fields
    def _get_field(self, ftype, name):
        res = super(RecordRelations, self)._get_field(ftype, name)
        if ftype == 'many2one':
            return self._get_many2one_rel_obj(name, res)
        if ftype in ('one2many', 'many2many'):
            return self._get_one2many_rel_obj(name, res)
        return res

    def refresh(self):
        """Reread data and clean-up the caches

           :returns: self
           :rtype: instance of Record
        """
        super(RecordRelations, self).refresh()

        # Update related objects cache
        rel_objects = self._related_objects
        self._related_objects = {}

        for rel in rel_objects.itervalues():
            if isinstance(rel, (Record, RecordList)):
                rel.refresh()  # both, Record and RecordList objects have 'refresh* method
        return self


class ObjectRecords(Object):
    """ Adds support to use records from Object classes
    """

    def __init__(self, *args, **kwargs):
        super(ObjectRecords, self).__init__(*args, **kwargs)
        self._model = None

    @property
    def model(self):
        """ Returns Record instance of model related to this object.
            Useful to get additional info on object, like is it transient or not.
        """
        if self._model is None:
            res = self.proxy.get_obj('ir.model').search_records([('model', '=', self.name)], limit=2)
            assert res.length == 1, "There must be only one model for this name"
            self._model = res[0]

        return self._model

    @property
    def model_name(self):
        """ Result of name_get called on object's model
        """
        return self.model._name

    @property
    def simple_fields(self):
        """ List of simple fields which could be fetched fast enough

            This list contains all fields that are not function nor binary

            :type: list of strings
        """
        return [f for f, d in self.columns_info.iteritems()
                if d['type'] != 'binary' and not d.get('function', False)]

    def search_records(self, *args, **kwargs):
        """ Return instance or list of instances of Record class,
            making available to work with data simpler

            :param domain: list of tuples, specifying search domain
            :param int offset: optional number of results to skip inthe returned values (default:0)
            :param limit: optional max number of record in results (default: False)
            :type limit: int|False
            :param order: optional columns to sort
            :type order: str
            :param dict context: optional context to pass to *search* method
            :param count: if set to True, then only amount of recrods found will be returned. (default: False)
            :param read_fields: optional. specifies list of fields to read. (Not used at the moment)
            :type read_fields: list of strings
            :return: RecordList contains records found, or integer representing amount of records found (if count=True)
            :rtype: RecordList|int

            >>> so_obj = db['sale.order']
            >>> data = so_obj.search_records([('date','>=','2013-01-01')])
            >>> for order in data:
                    order.write({'note': 'order date is %s'%order.date})
        """

        read_fields = kwargs.pop('read_fields', None)
        context = kwargs.get('context', None)

        if kwargs.get('count', False):
            return self.search(*args, **kwargs)

        res = self.search(*args, **kwargs)
        if not res:
            return get_record_list(self, ids=[], fields=read_fields, context=context)

        if read_fields:
            return self.read_records(res, read_fields, context=context)
        return self.read_records(res, context=context)

    def read_records(self, ids, fields=None, context=None, cache=None):
        """ Return instance or RecordList class,
            making available to work with data simpler

            :param ids: ID or list of IDS to read data for
            :type ids: int|list of int
            :param list fields: list of fields to read (*optional*)
            :param dict context: context to be passed to read. default=None
            :param cache: cache to use for records and record lists.
                          Pass None to create new cache. default=None.
            :return: Record instance if *ids* is int or RecordList instance
                     if *ids* is list of ints
            :rtype: Record|RecordList

            >>> so_obj = db['sale.order']
            >>> data = so_obj.read_records([1,2,3,4,5])
            >>> for order in data:
                    order.write({'note': 'order data is %s'%order.data})
        """
        assert isinstance(ids, (int, long, list, tuple)), "ids must be instance of (int, long, list, tuple)"

        if isinstance(ids, (int, long)):
            record = get_record(self, ids, context=context)
            if fields is not None:
                record.read(fields)  # read specified fields
            return record
        if isinstance(ids, (list, tuple)):
            return get_record_list(self, ids, fields=fields, context=context)

        raise ValueError("Wrong type for ids args")

    def browse(self, *args, **kwargs):
        """ Aliase to *read_records* method. In most cases same as serverside *browse*
            (i mean server version 7.0)
        """
        return self.read_records(*args, **kwargs)
