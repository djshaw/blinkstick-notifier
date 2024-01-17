import heapq

class Heap:
    """
    Convenience class for simplifying heapq usage
    """

    def __init__( self, array=None, heapify=True ):
        if array:
            self.heap = array
            if heapify:
                heapq.heapify( self.heap )
        else:
            self.heap = []

    def push( self, x ):
        heapq.heappush( self.heap, x )

    def pop( self ):
        return heapq.heappop( self.heap )

    def size( self ):
        return len( self.heap )

    def peek( self ):
        return self.heap[0].value


class HeapBy( Heap ):
    # Item only uses the key function to sort elements,
    # just in case the values are not comparable
    class Item:
        def __init__( self, value, key ):
            self.key = key
            self.value = value

        def __lt__( self, other ):
            return self.key( self.value ) < other.key( other.value )

    def __init__( self, key, array=None, heapify=True ):
        super().__init__( array, heapify )
        self.key = key

    def push( self, x ):
        super().push( self.Item( x, self.key ) )

    def pop( self ):
        return super().pop().value


