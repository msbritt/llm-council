import { useState } from 'react';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onRenameConversation,
  onDeleteConversation,
}) {
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState('');

  const startEditing = (conv, e) => {
    e.stopPropagation(); // Don't select the conversation
    setEditingId(conv.id);
    setEditTitle(conv.title || 'New Conversation');
  };

  const cancelEditing = () => {
    setEditingId(null);
    setEditTitle('');
  };

  const saveTitle = (id) => {
    if (editTitle.trim()) {
      onRenameConversation(id, editTitle.trim());
    }
    cancelEditing();
  };

  const handleKeyDown = (e, id) => {
    if (e.key === 'Enter') {
      saveTitle(id);
    } else if (e.key === 'Escape') {
      cancelEditing();
    }
  };

  const handleDelete = (id, e) => {
    e.stopPropagation(); // Don't select the conversation
    onDeleteConversation(id);
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h1>LLM Council</h1>
        <button className="new-conversation-btn" onClick={onNewConversation}>
          + New Conversation
        </button>
      </div>

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="no-conversations">No conversations yet</div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                conv.id === currentConversationId ? 'active' : ''
              }`}
              onClick={() => editingId !== conv.id && onSelectConversation(conv.id)}
            >
              {editingId === conv.id ? (
                <div className="conversation-edit">
                  <input
                    type="text"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    onKeyDown={(e) => handleKeyDown(e, conv.id)}
                    onBlur={() => saveTitle(conv.id)}
                    autoFocus
                    className="edit-title-input"
                  />
                </div>
              ) : (
                <>
                  <div className="conversation-title">
                    {conv.title || 'New Conversation'}
                  </div>
                  <div className="conversation-meta">
                    {conv.message_count} messages
                  </div>
                  <div className="conversation-actions">
                    <button
                      className="action-btn rename-btn"
                      onClick={(e) => startEditing(conv, e)}
                      title="Rename"
                    >
                      &#9998;
                    </button>
                    <button
                      className="action-btn delete-btn"
                      onClick={(e) => handleDelete(conv.id, e)}
                      title="Delete"
                    >
                      &#128465;
                    </button>
                  </div>
                </>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
