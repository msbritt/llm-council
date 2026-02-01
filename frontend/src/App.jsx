import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import { api } from './api';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [pendingClarification, setPendingClarification] = useState(null);
  const [iterationPhase, setIterationPhase] = useState({
    active: false,
    maxIterations: 3,
    modelStates: {}, // {modelId: {round: N, status: 'thinking'|'ready'}}
    pendingQuestions: null
  });

  // Load conversations on mount
  useEffect(() => {
    loadConversations();
  }, []);

  // Load conversation details when selected
  useEffect(() => {
    if (currentConversationId) {
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  const handleNewConversation = async () => {
    try {
      const newConv = await api.createConversation();
      setConversations([
        { id: newConv.id, created_at: newConv.created_at, message_count: 0 },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
  };

  const handleRenameConversation = async (id, newTitle) => {
    try {
      await api.renameConversation(id, newTitle);
      // Update local state
      setConversations((prev) =>
        prev.map((conv) =>
          conv.id === id ? { ...conv, title: newTitle } : conv
        )
      );
    } catch (error) {
      console.error('Failed to rename conversation:', error);
    }
  };

  const handleDeleteConversation = async (id) => {
    // Confirm before deleting
    if (!window.confirm('Are you sure you want to delete this conversation?')) {
      return;
    }

    try {
      await api.deleteConversation(id);
      // Remove from local state
      setConversations((prev) => prev.filter((conv) => conv.id !== id));
      // If deleting the current conversation, clear selection
      if (currentConversationId === id) {
        setCurrentConversationId(null);
        setCurrentConversation(null);
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error);
    }
  };

  const handleSendMessage = async (content, clarifications = null) => {
    if (!currentConversationId) return;

    setIsLoading(true);
    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));

      // Create a partial assistant message that will be updated progressively
      const assistantMessage = {
        role: 'assistant',
        stage0: clarifications?.stage0_data || null,
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
        clarifications: clarifications,
        loading: {
          stage1: false,
          stage2: false,
          stage3: false,
        },
      };

      // Add the partial assistant message
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }));

      // Send message with streaming (pass clarifications if provided)
      await api.sendMessageStream(
        currentConversationId,
        content,
        (eventType, event) => {
        switch (eventType) {
          case 'phase_start':
            // Iteration or other phase starting
            if (event.phase === 'iteration') {
              setIterationPhase(prev => ({ ...prev, active: true }));
              console.log('Iteration phase started');
            }
            break;

          case 'questions_needed':
            // Models need answers during iteration
            setIterationPhase(prev => ({
              ...prev,
              pendingQuestions: event.questions
            }));
            break;

          case 'iteration_complete':
            // All models have finished iterating
            setIterationPhase(prev => ({
              ...prev,
              active: false,
              modelStates: event.states
            }));
            console.log('Iteration complete:', event.states);
            break;

          case 'stage0_start':
            // Stage 0 has started - collecting clarifying questions
            console.log('Stage 0 started: collecting clarifying questions');
            break;

          case 'stage0_questions_collected':
            // Models have returned their questions
            console.log('Stage 0 questions collected:', event.data);
            break;

          case 'stage0_research_start':
            // Research queries are being executed
            console.log('Stage 0 research started');
            break;

          case 'stage0_research_complete':
            // Research is done
            console.log('Stage 0 research complete:', event.data);
            break;

          case 'stage0_needs_user_input':
            // Backend is paused, waiting for user to answer questions
            // Store the data and stop the loading state
            setPendingClarification({
              userQuestions: event.user_questions || [],
              researchResults: event.research_results || {},
              stage0Raw: event.stage0_raw || [],
              originalQuery: content,
            });
            setIsLoading(false);
            break;

          case 'stage0_complete':
            // Stage 0 finished with no user input needed
            console.log('Stage 0 complete (no user input needed)');
            break;

          case 'stage1_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage1 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage1_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage1 = event.data;
              lastMsg.loading.stage1 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage2_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage2 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage2_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage2 = event.data;
              lastMsg.metadata = event.metadata;
              lastMsg.loading.stage2 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage3_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage3 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage3_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage3 = event.data;
              lastMsg.loading.stage3 = false;
              return { ...prev, messages };
            });
            break;

          case 'title_complete':
            // Reload conversations to get updated title
            loadConversations();
            break;

          case 'complete':
            // Stream complete, reload conversations list
            loadConversations();
            setIsLoading(false);
            break;

          case 'error':
            console.error('Stream error:', event.message);
            setIsLoading(false);
            break;

          default:
            console.log('Unknown event type:', eventType);
        }
      },
      clarifications
      );
    } catch (error) {
      console.error('Failed to send message:', error);
      // Remove optimistic messages on error
      setCurrentConversation((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, -2),
      }));
      setIsLoading(false);
    }
  };

  const handleClarificationSubmit = (answers) => {
    if (!pendingClarification) return;

    // Build the clarifications object that backend expects
    const clarifications = {
      user_answers: answers,
      research_results: pendingClarification.researchResults,
      stage0_data: {
        user_questions: pendingClarification.userQuestions,
        stage0_raw: pendingClarification.stage0Raw,
      },
    };

    // Clear the pending state
    const originalQuery = pendingClarification.originalQuery;
    setPendingClarification(null);

    // Re-send the original message with clarifications
    handleSendMessage(originalQuery, clarifications);
  };

  const handleClarificationSkip = () => {
    if (!pendingClarification) return;

    // Build clarifications with empty answers (backend will proceed without user input)
    const clarifications = {
      user_answers: {},
      research_results: pendingClarification.researchResults,
      stage0_data: {
        user_questions: pendingClarification.userQuestions,
        stage0_raw: pendingClarification.stage0Raw,
      },
    };

    // Clear the pending state
    const originalQuery = pendingClarification.originalQuery;
    setPendingClarification(null);

    // Re-send the original message with clarifications (but no answers)
    handleSendMessage(originalQuery, clarifications);
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onRenameConversation={handleRenameConversation}
        onDeleteConversation={handleDeleteConversation}
      />
      <ChatInterface
        conversation={currentConversation}
        onSendMessage={handleSendMessage}
        isLoading={isLoading}
        pendingClarification={pendingClarification}
        onClarificationSubmit={handleClarificationSubmit}
        onClarificationSkip={handleClarificationSkip}
      />
    </div>
  );
}

export default App;
