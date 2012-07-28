
from key import Key
from query import Cursor

class Datastore(object):
  '''A Datastore represents storage for any key-value pair.

  Datastores are general enough to be backed by all kinds of different storage:
  in-memory caches, databases, a remote datastore, flat files on disk, etc.

  The general idea is to wrap a more complicated storage facility in a simple,
  uniform interface, keeping the freedom of using the right tools for the job.
  In particular, a Datastore can aggregate other datastores in interesting ways,
  like sharded (to distribute load) or tiered access (caches before databases).

  While Datastores should be written general enough to accept all sorts of
  values, some implementations will undoubtedly have to be specific (e.g. SQL
  databases where fields should be decomposed into columns), particularly to
  support queries efficiently.

  '''

  # Main API. Datastore mplementations MUST implement these methods.

  def get(self, key):
    '''Return the object named by key or None if it does not exist.

    None takes the role of default value, so no KeyError exception is raised.

    Args:
      key: Key naming the object to retrieve

    Returns:
      object or None
    '''
    raise NotImplementedError

  def put(self, key, value):
    '''Stores the object `value` named by `key`.

    How to serialize and store objects is up to the underlying datastore.
    It is recommended to use simple objects (strings, numbers, lists, dicts).

    Args:
      key: Key naming `value`
      value: the object to store.
    '''
    raise NotImplementedError

  def delete(self, key):
    '''Removes the object named by `key`.

    Args:
      key: Key naming the object to remove.
    '''
    raise NotImplementedError

  def query(self, query):
    '''Returns an iterable of objects matching criteria expressed in `query`

    Implementations of query will be the largest differentiating factor
    amongst datastores. All datastores **must** implement query, even using
    query's worst case scenario, see :ref:class:`Query` for details.

    Args:
      query: Query object describing the objects to return.

    Raturns:
      iterable cursor with all objects matching criteria
    '''
    raise NotImplementedError

  # Secondary API. Datastores MAY provide optimized implementations.

  def contains(self, key):
    '''Returns whether the object named by `key` exists.

    The default implementation pays the cost of a get. Some datastore
    implementations may optimize this.

    Args:
      key: Key naming the object to check.

    Returns:
      boalean whether the object exists
    '''
    return self.get(key) is not None




class DictDatastore(Datastore):
  '''Simple straw-man in-memory datastore backed by nested dicts.'''

  def __init__(self):
    self._items = dict()

  def _collection(self, key):
    '''Returns the namespace collection for `key`.'''
    collection = str(key.path)
    if not collection in self._items:
      self._items[collection] = dict()
    return self._items[collection]

  def get(self, key):
    '''Return the object named by `key` or None.

    Retrieves the object from the collection corresponding to ``key.path``.

    Args:
      key: Key naming the object to retrieve.

    Returns:
      object or None
    '''
    try:
      return self._collection(key)[key]
    except KeyError, e:
      return None

  def put(self, key, value):
    '''Stores the object `value` named by `key`.

    Stores the object in the collection corresponding to ``key.path``.

    Args:
      key: Key naming `value`
      value: the object to store.
    '''
    if value is None:
      self.delete(key)
    else:
      self._collection(key)[key] = value

  def delete(self, key):
    '''Removes the object named by `key`.

    Removes the object from the collection corresponding to ``key.path``.

    Args:
      key: Key naming the object to remove.
    '''
    try:
      del self._collection(key)[key]

      if len(self._collection(key)) == 0:
        del self._items[str(key.path)]
    except KeyError, e:
      pass

  def contains(self, key):
    '''Returns whether the object named by `key` exists.

    Checks for the object in the collection corresponding to ``key.path``.

    Args:
      key: Key naming the object to check.

    Returns:
      boalean whether the object exists
    '''

    return key in self._collection(key)

  def query(self, query):
    '''Returns an iterable of objects matching criteria expressed in `query`

    Naively applies the query operations on the objects within the namespaced
    collection corresponding to ``query.key.path``.

    Args:
      query: Query object describing the objects to return.

    Raturns:
      iterable cursor with all objects matching criteria
    '''

    # entire dataset already in memory, so ok to apply query naively
    if str(query.key) in self._items:
      return query(self._items[str(query.key)].values())
    else:
      return query([])

  def __len__(self):
    return sum(map(len, self._items.values()))




class InterfaceMappingDatastore(Datastore):
  '''Represents simple wrapper datastore around an object that, though not a
  Datastore, implements data storage through a similar interface. For example,
  memcached and redis both implement a `get`, `set`, `delete` interface.
  '''

  def __init__(self, service, get='get', put='put', delete='delete', key=str):
    '''Initialize the datastore with given `service`.

    Args:
      service: A service that provides data storage through a similar interface
          to Datastore. Using the service should only require a simple mapping
          of methods, such as {put : set}.

      get:    The attribute name of the `service` method implementing get
      put:    The attribute name of the `service` method implementing put
      delete: The attribute name of the `service` method implementing delete

      key: A function converting a Datastore key (of type Key) into a `service`
          key. The conversion will often be as simple as `str`.
    '''
    self._service = service
    self._service_key = key

    self._service_ops = {}
    self._service_ops['get'] = getattr(service, get)
    self._service_ops['put'] = getattr(service, put)
    self._service_ops['delete'] = getattr(service, delete)
    # AttributeError will be raised if service does not implement the interface


  def get(self, key):
    '''Return the object in `service` named by `key` or None.

    Args:
      key: Key naming the object to retrieve.

    Returns:
      object or None
    '''
    key = self._service_key(key)
    return self._service_ops['get'](key)

  def put(self, key, value):
    '''Stores the object `value` named by `key` in `service`.

    Args:
      key: Key naming `value`.
      value: the object to store.
    '''
    key = self._service_key(key)
    self._service_ops['put'](key, value)

  def delete(self, key):
    '''Removes the object named by `key` in `service`.

    Args:
      key: Key naming the object to remove.
    '''
    key = self._service_key(key)
    self._service_ops['delete'](key)






class ShimDatastore(Datastore):
  '''Represents a non-concrete datastore that adds functionality between the
  client and a lower level datastore. Shim datastores do not actually store
  data themselves; instead, they delegate storage to an underlying child
  datastore. The default implementation just passes all calls to the child.
  '''

  def __init__(self, datastore):
    '''Initializes this ShimDatastore with child `datastore`.'''

    if not isinstance(datastore, Datastore):
      errstr = 'datastore must be of type %s. Got %s.'
      raise TypeError(errstr % (Datastore, datastore))

    self.child_datastore = datastore

  # default implementation just passes all calls to child
  def get(self, key):
    '''Return the object named by key or None if it does not exist.

    Default shim implementation simply returns ``child_datastore.get(key)``
    Override to provide different functionality, for example::

        def get(self, key):
          value = self.child_datastore.get(key)
          return json.loads(value)

    Args:
      key: Key naming the object to retrieve

    Returns:
      object or None
    '''
    return self.child_datastore.get(key)

  def put(self, key, value):
    '''Stores the object `value` named by `key`.

    Default shim implementation simply calls ``child_datastore.put(key, value)``
    Override to provide different functionality, for example::

        def put(self, key, value):
          value = json.dumps(value)
          self.child_datastore.put(key, value)

    Args:
      key: Key naming `value`.
      value: the object to store.
    '''
    self.child_datastore.put(key, value)

  def delete(self, key):
    '''Removes the object named by `key`.

    Default shim implementation simply calls ``child_datastore.delete(key)``
    Override to provide different functionality.

    Args:
      key: Key naming the object to remove.
    '''
    self.child_datastore.delete(key)

  def query(self, query):
    '''Returns an iterable of objects matching criteria expressed in `query`.

    Default shim implementation simply returns ``child_datastore.query(query)``
    Override to provide different functionality, for example::

        def query(self, query):
          cursor = self.child_datastore.query(query)
          cursor._iterable = deserialized(cursor._iterable)
          return cursor

    Args:
      query: Query object describing the objects to return.

    Raturns:
      iterable cursor with all objects matching criteria
    '''
    return self.child_datastore.query(query)



class KeyTransformDatastore(ShimDatastore):
  '''Represents a simple ShimDatastore that applies a transform on all incoming
     keys. For example:

       >>> import datastore
       >>> def transform(key):
       ...   return key.reverse
       ...
       >>> ds = datastore.DictDatastore()
       >>> kt = datastore.KeyTransformDatastore(ds, keytransform=transform)
       None
       >>> ds.put(datastore.Key('/a/b/c'), 'abc')
       >>> ds.get(datastore.Key('/a/b/c'))
       'abc'
       >>> kt.get(datastore.Key('/a/b/c'))
       None
       >>> kt.get(datastore.Key('/c/b/a'))
       'abc'
       >>> ds.get(datastore.Key('/c/b/a'))
       None

  '''

  def __init__(self, *args, **kwargs):
    '''Initializes KeyTransformDatastore with `keytransform` function.'''
    self.keytransform = kwargs.pop('keytransform', None)
    super(KeyTransformDatastore, self).__init__(*args, **kwargs)

  def get(self, key):
    '''Return the object named by keytransform(key).'''
    return self.child_datastore.get(self._transform(key))

  def put(self, key, value):
    '''Stores the object names by keytransform(key).'''
    return self.child_datastore.put(self._transform(key), value)

  def delete(self, key):
    '''Removes the object named by keytransform(key).'''
    return self.child_datastore.delete(self._transform(key))

  def contains(self, key):
    '''Returns whether the object named by key is in this datastore.'''
    return self.child_datastore.contains(self._transform(key))

  def query(self, query):
    '''Returns a sequence of objects matching criteria expressed in `query`'''
    query = query.copy()
    query.key = self._transform(query.key)
    return self.child_datastore.query(query)

  def _transform(self, key):
    '''Returns a `key` transformed by `self.keytransform`.'''
    return self.keytransform(key) if self.keytransform else key



class LowercaseKeyDatastore(KeyTransformDatastore):
  '''Represents a simple ShimDatastore that lowercases all incoming keys.
     For example:

      >>> import datastore
      >>> ds = datastore.DictDatastore()
      >>> ds.put(datastore.Key('hello'), 'world')
      >>> ds.put(datastore.Key('HELLO'), 'WORLD')
      >>> ds.get(datastore.Key('hello'))
      'world'
      >>> ds.get(datastore.Key('HELLO'))
      'WORLD'
      >>> ds.get(datastore.Key('HeLlO'))
      None
      >>> lds = datastore.LowercaseKeyDatastore(ds)
      >>> lds.get(datastore.Key('HeLlO'))
      'world'
      >>> lds.get(datastore.Key('HeLlO'))
      'world'
      >>> lds.get(datastore.Key('HeLlO'))
      'world'

  '''

  def __init__(self, *args, **kwargs):
    '''Initializes KeyTransformDatastore with keytransform function.'''
    super(LowercaseKeyDatastore, self).__init__(*args, **kwargs)
    self.keytransform = self.lowercaseKey

  @classmethod
  def lowercaseKey(cls, key):
    '''Returns a lowercased `key`.'''
    return Key(str(key).lower())



class NamespaceDatastore(KeyTransformDatastore):
  '''Represents a simple ShimDatastore that namespaces all incoming keys.
     For example:

      >>> import datastore
      >>>
      >>> ds = datastore.DictDatastore()
      >>> ds.put(datastore.Key('/a/b'), 'ab')
      >>> ds.put(datastore.Key('/c/d'), 'cd')
      >>> ds.put(datastore.Key('/a/b/c/d'), 'abcd')
      >>>
      >>> nd = datastore.NamespaceDatastore('/a/b', ds)
      >>> nd.get(datastore.Key('/a/b'))
      None
      >>> nd.get(datastore.Key('/c/d'))
      'abcd'
      >>> nd.get(datastore.Key('/a/b/c/d'))
      None
      >>> nd.put(datastore.Key('/c/d'), 'cd')
      >>> ds.get(datastore.Key('/a/b/c/d'))
      'cd'

  '''

  def __init__(self, namespace, *args, **kwargs):
    '''Initializes NamespaceDatastore with `key` namespace.'''
    super(NamespaceDatastore, self).__init__(*args, **kwargs)
    self.keytransform = self.namespaceKey
    self.namespace = Key(namespace)

  def namespaceKey(self, key):
    '''Returns a namespaced `key`: namespace.child(key).'''
    return self.namespace.child(key)





class NestedPathDatastore(KeyTransformDatastore):
  '''Represents a simple ShimDatastore that shards/namespaces incoming keys.

    Incoming keys are sharded into nested namespaces. The idea is to use the key
    name to separate into nested namespaces. This is akin to the directory
    structure that ``git`` uses for objects. For example:

    >>> import datastore
    >>>
    >>> ds = datastore.DictDatastore()
    >>> np = datastore.NestedPathDatastore(ds, depth=3, length=2)
    >>>
    >>> np.put(datastore.Key('/abcdefghijk'), 1)
    >>> np.get(datastore.Key('/abcdefghijk'))
    1
    >>> ds.get(datastore.Key('/abcdefghijk'))
    None
    >>> ds.get(datastore.Key('/ab/cd/ef/abcdefghijk'))
    1
    >>> np.put(datastore.Key('abc'), 2)
    >>> np.get(datastore.Key('abc'))
    2
    >>> ds.get(datastore.Key('/ab/ca/bc/abc'))
    2

  '''

  _default_depth = 3
  _default_length = 2
  _default_keyfn = lambda key: key.name
  _default_keyfn = staticmethod(_default_keyfn)

  def __init__(self, *args, **kwargs):
    '''Initializes KeyTransformDatastore with keytransform function.

    kwargs:
      depth: the nesting level depth (e.g. 3 => /1/2/3/123) default: 3
      length: the nesting level length (e.g. 2 => /12/123456) default: 2
    '''

    # assign the nesting variables
    self.nest_depth = kwargs.pop('depth', self._default_depth)
    self.nest_length = kwargs.pop('length', self._default_length)
    self.nest_keyfn = kwargs.pop('keyfn', self._default_keyfn)

    super(NestedPathDatastore, self).__init__(*args, **kwargs)
    self.keytransform = self.nestKey

  def query(self, query):
    # Requires supporting * operator on queries.
    raise NotImplementedError

  def nestKey(self, key):
    '''Returns a nested `key`.'''

    nest = self.nest_keyfn(key)

    # if depth * length > len(key.name), we need to pad.
    mult = 1 + int(self.nest_depth * self.nest_length / len(nest))
    nest = nest * mult

    pref = Key(self.nestedPath(nest, self.nest_depth, self.nest_length))
    return pref.child(key)

  @staticmethod
  def nestedPath(path, depth, length):
    '''returns a nested version of `basename`, using the starting characters.
      For example:

        >>> NestedPathDatastore.nested_path('abcdefghijk', 3, 2)
        'ab/cd/ef'
        >>> NestedPathDatastore.nested_path('abcdefghijk', 4, 2)
        'ab/cd/ef/gh'
        >>> NestedPathDatastore.nested_path('abcdefghijk', 3, 4)
        'abcd/efgh/ijk'
        >>> NestedPathDatastore.nested_path('abcdefghijk', 1, 4)
        'abcd'
        >>> NestedPathDatastore.nested_path('abcdefghijk', 3, 10)
        'abcdefghij/k'
    '''
    components = [path[n:n+length] for n in xrange(0, len(path), length)]
    components = components[:depth]
    return '/'.join(components)





class DatastoreCollection(ShimDatastore):
  '''Represents a collection of datastores.'''

  def __init__(self, stores=[]):
    '''Initialize the datastore with any provided datastores.'''
    if not isinstance(stores, list):
      stores = list(stores)

    for store in stores:
      if not isinstance(store, Datastore):
        raise TypeError("all stores must be of type %s" % Datastore)

    self._stores = stores

  def datastore(self, index):
    '''Returns the datastore at `index`.'''
    return self._stores[index]

  def appendDatastore(self, store):
    '''Appends datastore `store` to this collection.'''
    if not isinstance(store, Datastore):
      raise TypeError("stores must be of type %s" % Datastore)

    self._stores.append(store)

  def removeDatastore(self, store):
    '''Removes datastore `store` from this collection.'''
    self._stores.remove(store)

  def insertDatastore(self, index, store):
    '''Inserts datastore `store` into this collection at `index`.'''
    if not isinstance(store, Datastore):
      raise TypeError("stores must be of type %s" % Datastore)

    self._stores.insert(index, store)





class TieredDatastore(DatastoreCollection):
  '''Represents a hierarchical collection of datastores.

  Each datastore is queried in order. This is helpful to organize access
  order in terms of speed (i.e. read caches first).

  Datastores should be arranged in order of completeness, with the most complete
  datastore last, as it will handle query calls.

  Semantics:
    * get      : returns first found value
    * put      : writes through to all
    * delete   : deletes through to all
    * contains : returns first found value
    * query    : queries bottom (most complete) datastore

  '''

  def get(self, key):
    '''Return the object named by key. Checks each datastore in order.'''
    value = None
    for store in self._stores:
      value = store.get(key)
      if value is not None:
        break

    # add model to lower stores only
    if value is not None:
      for store2 in self._stores:
        if store == store2:
          break
        store2.put(key, value)

    return value

  def put(self, key, value):
    '''Stores the object in all underlying datastores.'''
    for store in self._stores:
      store.put(key, value)

  def delete(self, key):
    '''Removes the object from all underlying datastores.'''
    for store in self._stores:
      store.delete(key)

  def query(self, query):
    '''Returns a sequence of objects matching criteria expressed in `query`.
    The last datastore will handle all query calls, as it has a (if not
    the only) complete record of all objects.
    '''
    # queries hit the last (most complete) datastore
    return self._stores[-1].query(query)

  def contains(self, key):
    '''Returns whether the object is in this datastore.'''
    for store in self._stores:
      if store.contains(key):
        return True
    return False





class ShardedDatastore(DatastoreCollection):
  '''Represents a collection of datastore shards.

  A datastore is selected based on a sharding function.
  Sharding functions should take a Key and return an integer.

  WARNING: adding or removing datastores while mid-use may severely affect
           consistency. Also ensure the order is correct upon initialization.
           While this is not as important for caches, it is crucial for
           persistent datastores.

  '''

  def __init__(self, stores=[], shardingfn=hash):
    '''Initialize the datastore with any provided datastore.'''
    if not callable(shardingfn):
      raise TypeError('shardingfn (type %s) is not callable' % type(shardingfn))

    super(ShardedDatastore, self).__init__(stores)
    self._shardingfn = shardingfn


  def shard(self, key):
    '''Returns the shard index to handle `key`, according to sharding fn.'''
    return self._shardingfn(key) % len(self._stores)

  def shardDatastore(self, key):
    '''Returns the shard to handle `key`.'''
    return self.datastore(self.shard(key))


  def get(self, key):
    '''Return the object named by key from the corresponding datastore.'''
    return self.shardDatastore(key).get(key)

  def put(self, key, value):
    '''Stores the object to the corresponding datastore.'''
    self.shardDatastore(key).put(key, value)

  def delete(self, key):
    '''Removes the object from the corresponding datastore.'''
    self.shardDatastore(key).delete(key)

  def contains(self, key):
    '''Returns whether the object is in this datastore.'''
    return self.shardDatastore(key).contains(key)

  def query(self, query):
    '''Returns a sequence of objects matching criteria expressed in `query`'''
    cursor = Cursor(query, self.shard_query_generator(query))
    cursor.apply_order()  # ordering sharded queries is expensive (no generator)
    return cursor

  def shard_query_generator(self, query):
    '''A generator that queries each shard in sequence.'''
    shard_query = query.copy()

    for shard in self._stores:
      # yield all items matching within this shard
      cursor = shard.query(shard_query)
      for item in cursor:
        yield item

      # update query with results of first query
      shard_query.offset = max(shard_query.offset - cursor.skipped, 0)
      if shard_query.limit:
        shard_query.limit = max(shard_query.limit - cursor.returned, 0)

        if shard_query.limit <= 0:
          break  # we're already done!


'''

Hello Tiered Access

    >>> import pymongo
    >>> import datastore
    >>>
    >>> from datastore.impl.mongo import MongoDatastore
    >>> from datastore.impl.lrucache import LRUCache
    >>> from datastore.impl.filesystem import FileSystemDatastore
    >>>
    >>> conn = pymongo.Connection()
    >>> mongo = MongoDatastore(conn.test_db)
    >>>
    >>> cache = LRUCache(1000)
    >>> fs = FileSystemDatastore('/tmp/.test_db')
    >>>
    >>> ds = datastore.TieredDatastore([cache, mongo, fs])
    >>>
    >>> hello = datastore.Key('hello')
    >>> ds.put(hello, 'world')
    >>> ds.contains(hello)
    True
    >>> ds.get(hello)
    'world'
    >>> ds.delete(hello)
    >>> ds.get(hello)
    None

Hello Sharding

    >>> import datastore
    >>>
    >>> shards = [datastore.DictDatastore() for i in range(0, 10)]
    >>>
    >>> ds = datastore.ShardedDatastore(shards)
    >>>
    >>> hello = datastore.Key('hello')
    >>> ds.put(hello, 'world')
    >>> ds.contains(hello)
    True
    >>> ds.get(hello)
    'world'
    >>> ds.delete(hello)
    >>> ds.get(hello)
    None

'''
