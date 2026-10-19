// Compatibility for existing Node imports; all calculations live in Python.
import { legacyProxy } from './legacy-proxy.js';
export default legacyProxy('/api/market');
