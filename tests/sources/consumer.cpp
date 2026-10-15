#include "fixture.h"

int main()
{
	const fixture::square stack{ 2.0 };
	fixture::square* heap = new fixture::square{ 3.0 };
	const fixture::square scaled = *heap * 2.0;
	const int doubled = fixture::doubler{}(static_cast<bool>(scaled) ? 1 : 0);
	const int result = fixture::add(static_cast<int>(stack.area()), fixture::twice(versioned_answer())) + doubled;
	delete heap;
	return result;
}
