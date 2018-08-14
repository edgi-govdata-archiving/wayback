class UndiffableContentError(ValueError):
    """
    Raised when the content provided to a differ is incompatible with the
    diff algorithm. For example, if a PDF was provided to an HTML differ.
    """
